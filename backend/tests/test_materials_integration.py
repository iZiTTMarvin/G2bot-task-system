from __future__ import annotations

import io

import pytest
from openpyxl import load_workbook

from app.tools.validation import validate_content
from tests.conftest import generate, make_batch
from tests.test_runs import ScriptedClient, _install


def _desk_task(materials):
    return {
        "name": "办公桌-整理桌面文具",
        "steps": [
            "把【笔记本】从桌面中间移到桌面左侧",
            "将【笔记本】的前边与桌面边线对齐",
            "把【便签】从桌面右侧移到【笔记本】前方居中位置",
            "将【便签】整摞的边缘对齐",
            "把【笔筒】从桌面右侧移到桌面右上角",
            "将【笔筒】摆正",
            "从桌面上拿起【笔1】",
            "将【笔1】移到【笔筒】口上方",
            "把【笔1】放入【笔筒】",
            "从桌面上拿起【笔2】",
            "将【笔2】移到【笔筒】口上方",
            "把【笔2】放入【笔筒】",
        ],
        "materials": materials,
    }


@pytest.mark.parametrize(
    ("pens", "mismatch"),
    [
        ([{"name": "笔1", "quantity": 1}, {"name": "笔2", "quantity": 1}], False),
        ([{"name": "笔", "quantity": 2}], False),
        ([{"name": "笔1", "quantity": 1}], True),
        ([{"name": "笔", "quantity": 3}], True),
        ([{"name": "笔", "quantity": 2}, {"name": "橡皮", "quantity": 1}], True),
    ],
)
def test_numbered_and_grouped_materials_are_compared_by_quantity(pens, mismatch):
    task = _desk_task([
        {"name": "笔记本", "quantity": 1},
        {"name": "便签", "quantity": 1},
        {"name": "笔筒", "quantity": 1},
        *pens,
    ])
    report = validate_content(task, "standard", "test-snapshot")
    material_issues = [issue for issue in report["issues"] if issue["code"] == "MATERIALS_MISMATCH"]
    assert bool(material_issues) is mismatch, material_issues


def test_numbered_materials_flow_through_review_and_export(client, monkeypatch):
    content = _desk_task([
        {"name": "笔记本", "quantity": 1},
        {"name": "笔1", "quantity": 1},
        {"name": "笔2", "quantity": 1},
        {"name": "便签", "quantity": 1},
        {"name": "笔筒", "quantity": 1},
    ])
    _install(monkeypatch, ScriptedClient(gen_payload=[content]))
    batch = make_batch(client, count=1, mode="standard")
    assert generate(client, batch["id"])["status"] == "succeeded"
    task = client.get("/api/v1/tasks").json()["items"][0]
    assert task["status"] == "human_pending"
    detail = client.get(f"/api/v1/tasks/{task['id']}").json()
    assert detail["current_version"]["content"] == content
    decision = client.post(
        f"/api/v1/tasks/{task['id']}/decisions",
        json={"expected_revision": detail["summary"]["revision"],
              "version_id": detail["current_version"]["id"], "decision": "approve"},
        headers={"Idempotency-Key": "numbered-material-decision"},
    )
    assert decision.status_code == 201
    exported = client.post(
        "/api/v1/exports",
        json={"batch_id": batch["id"], "task_ids": [task["id"]]},
        headers={"Idempotency-Key": "numbered-material-export"},
    )
    assert exported.status_code == 201
    download = client.get(exported.json()["download_url"])
    assert download.status_code == 200
    sheet = load_workbook(io.BytesIO(download.content)).active
    assert sheet.cell(2, 3).value == "笔记本1个、笔2个、便签1个、笔筒1个"


def test_invalid_ai_optimization_does_not_replace_valid_original(client, monkeypatch):
    original = _desk_task([
        {"name": "笔记本", "quantity": 1},
        {"name": "笔", "quantity": 2},
        {"name": "便签", "quantity": 1},
        {"name": "笔筒", "quantity": 1},
    ])
    invalid = {**original, "steps": [step.replace("【笔1】", "【笔】").replace("【笔2】", "【笔】")
                                    for step in original["steps"]]}

    class InvalidOptimization(ScriptedClient):
        def review_task(self, **kw):
            return {"verdict": "pass", "issues": [], "summary": "已优化", "optimized_task": invalid}

    _install(monkeypatch, InvalidOptimization(gen_payload=[original]))
    batch = make_batch(client, count=1, mode="standard")
    assert generate(client, batch["id"])["status"] == "succeeded"
    task = client.get("/api/v1/tasks").json()["items"][0]
    detail = client.get(f"/api/v1/tasks/{task['id']}").json()
    assert task["status"] == "ai_rejected"
    assert detail["current_version"]["content"] == original
    assert detail["current_version"]["validation"]["status"] == "passed"
    assert '保留' in detail["latest_review"]["summary"]
