import pytest


def task(name, steps):
    return {"name": name, "steps": steps, "materials": [{"name": "物品", "quantity": 1}]}


def test_exact_steps_are_duplicate_even_when_reordered():
    from app.tools.validation import compare_batch

    steps = ["拿起桌面上的【瓶子】", "打开【瓶子】的瓶盖", "把【瓶子】放到桌面上"]
    pair = compare_batch([task("甲", steps), task("乙", list(reversed(steps)))])[0]
    assert pair["exact_duplicate"] is True


def test_different_objects_are_not_collapsed_and_half_difference_is_allowed():
    from app.tools.validation import compare_batch, evaluate_step_matches

    shared = [f"打开【盒子{i}】" for i in range(5)]
    left = shared + [f"拿起桌面上的【瓶子{i}】" for i in range(5)]
    right = shared + [f"拿起桌面上的【书本{i}】" for i in range(5)]
    pair = compare_batch([task("甲", left), task("乙", right)])[0]
    assert pair["exact_duplicate"] is False
    assert pair["literal_matched_count"] == 5
    assert pair["literal_difference_ratio"] == 0.5
    assert pair["similar_step_examples"][0]["left_step_no"] == 1
    assert pair["similar_step_examples"][0]["right_step_no"] == 1

    result = evaluate_step_matches(left, right, [(i, i) for i in range(1, 6)])
    assert result["difference_ratio"] == 0.5
    assert result["meets_difference_target"] is True
    assert "【瓶子0】" in result["unmatched_left"][0]["step"]
    assert "【书本0】" in result["unmatched_right"][0]["step"]


def test_step_match_indices_are_one_to_one_and_in_bounds():
    from app.tools.validation import evaluate_step_matches

    with pytest.raises(ValueError):
        evaluate_step_matches(["甲", "乙"], ["丙", "丁"], [(1, 1), (1, 2)])
    with pytest.raises(ValueError):
        evaluate_step_matches(["甲"], ["乙"], [(2, 1)])


def test_difference_uses_longer_task_and_single_task_needs_no_comparison():
    from app.tools.validation import compare_batch, evaluate_step_matches

    left = [f"步骤{i}" for i in range(10)]
    right = [f"步骤{i}" for i in range(12)]
    assert compare_batch([task("单条", left)]) == []
    result = evaluate_step_matches(left, right, [(i, i) for i in range(1, 7)])
    assert result["difference_ratio"] == 0.5
    assert result["meets_difference_target"] is True


def test_long_task_has_no_default_step_limit():
    from app.api.schemas import TaskContentIn
    from app.agents.fake import _content
    from app.services.tasks import normalize_content
    from app.tools.validation import rule_snapshot_id, validate_content

    content = _content(1, "", "standard")
    content["steps"] = content["steps"] * 10
    assert len(TaskContentIn(**content).steps) > 100
    assert len(normalize_content(content)["steps"]) > 100
    report = validate_content(content, "long", rule_snapshot_id())
    assert not any("超过上限" in issue["message"] for issue in report["issues"])


def test_short_long_task_is_a_workload_warning_not_a_step_count_block():
    from app.agents.fake import _content
    from app.tools.validation import rule_snapshot_id, validate_content

    report = validate_content(_content(1, "", "standard"), "long", rule_snapshot_id())
    assert any(issue["severity"] == "warning" and "30" in issue["message"] for issue in report["issues"])
    assert not any(issue["severity"] == "error" and "步骤数" in issue["message"] for issue in report["issues"])


def test_final_batch_duplicate_is_visible_and_cannot_be_confirmed(client, monkeypatch):
    from app.agents.fake import _content
    from tests.conftest import generate, make_batch
    from tests.test_runs import ScriptedClient, _install

    original = _content(1, "", "standard")
    duplicate = {**original, "name": "模拟基地-重复任务", "steps": list(reversed(original["steps"]))}
    _install(monkeypatch, ScriptedClient(gen_payload=[original, duplicate]))
    batch = make_batch(client, count=2, mode="standard")
    assert generate(client, batch["id"])["status"] == "succeeded"
    tasks = client.get("/api/v1/tasks", params={"batch_id": batch["id"]}).json()["items"]
    assert all(item["batch_comparison"] == "duplicate" for item in tasks)
    assert all(item["status"] == "ai_rejected" for item in tasks)
    detail = client.get(f"/api/v1/tasks/{tasks[0]['id']}").json()
    assert any(item["code"] == "BATCH_EXACT_DUPLICATE" for item in detail["batch_issues"])
    decision = client.post(
        f"/api/v1/tasks/{tasks[0]['id']}/decisions",
        json={"expected_revision": detail["summary"]["revision"],
              "version_id": detail["current_version"]["id"], "decision": "approve"},
        headers={"Idempotency-Key": "duplicate-decision"},
    )
    assert decision.status_code == 422
    assert decision.json()["error"]["code"] == "RULE_GATE_FAILED"


def test_partial_similarity_is_a_warning_and_can_be_confirmed(client, monkeypatch):
    import io

    from openpyxl import load_workbook
    from app.agents.fake import _content
    from app.tools.skill_bundle import load_bundle
    from app.tools.validation import steps_to_text
    from tests.conftest import generate, make_batch
    from tests.test_runs import ScriptedClient, _install

    left = _content(1, "", "standard")
    right = {**left, "name": "模拟基地-收纳另一组用品", "steps": [
        step if index < len(left["steps"]) // 2 else
        step.replace("【模拟物品10】", "【另一物品1】").replace("【模拟物品11】", "【另一物品2】")
        for index, step in enumerate(left["steps"])
    ]}
    pairs = load_bundle().module("materials").derive_materials(steps_to_text(right["steps"]))
    right["materials"] = [{"name": name, "quantity": count} for name, count in pairs]
    _install(monkeypatch, ScriptedClient(gen_payload=[left, right]))
    batch = make_batch(client, count=2, mode="standard")
    assert generate(client, batch["id"])["status"] == "succeeded"
    tasks = client.get("/api/v1/tasks", params={"batch_id": batch["id"]}).json()["items"]
    assert all(item["batch_comparison"] == "similar" for item in tasks)
    details = [client.get(f"/api/v1/tasks/{item['id']}").json() for item in tasks]
    assert all(item["status"] == "human_pending" for item in tasks), [
        (item["summary"]["status"], item["current_version"]["validation"]["issues"]) for item in details
    ]
    detail = client.get(f"/api/v1/tasks/{tasks[0]['id']}").json()
    assert any(item["code"] == "BATCH_SIMILARITY" and item["severity"] == "warning"
               for item in detail["batch_issues"])
    assert any("本任务第" in item["message"] and "对方第" in item["message"]
               for item in detail["batch_issues"])
    decision = client.post(
        f"/api/v1/tasks/{tasks[0]['id']}/decisions",
        json={"expected_revision": detail["summary"]["revision"],
              "version_id": detail["current_version"]["id"], "decision": "approve"},
        headers={"Idempotency-Key": "similarity-decision"},
    )
    assert decision.status_code == 201
    exported = client.post(
        "/api/v1/exports", json={"batch_id": batch["id"], "task_ids": [tasks[0]["id"]]},
        headers={"Idempotency-Key": "similarity-export"},
    )
    assert exported.status_code == 201
    sheet = load_workbook(io.BytesIO(client.get(exported.json()["download_url"]).content)).active
    assert sheet.cell(2, 5).value.count("同批对比：") == 1


def test_review_changes_are_rechecked_against_final_batch(client, monkeypatch):
    from app.agents.fake import _content
    from tests.conftest import generate, make_batch
    from tests.test_runs import ScriptedClient, _install

    left = _content(1, "", "standard")
    right = _content(2, "", "standard")

    class DuplicateByReview(ScriptedClient):
        def review_task(self, *, content, **kw):
            assert "同批其他当前任务" in kw["reference_text"]
            optimized = left if content["name"] == right["name"] else None
            return {"verdict": "pass", "issues": [], "summary": "已审核", "optimized_task": optimized}

    _install(monkeypatch, DuplicateByReview(gen_payload=[left, right]))
    batch = make_batch(client, count=2, mode="standard")
    assert generate(client, batch["id"])["status"] == "succeeded"
    tasks = client.get("/api/v1/tasks", params={"batch_id": batch["id"]}).json()["items"]
    assert all(item["batch_comparison"] == "duplicate" and item["status"] == "ai_rejected"
               for item in tasks)


def test_manual_edit_rechecks_current_batch_before_approval(client, monkeypatch):
    from app.agents.fake import _content
    from tests.conftest import generate, make_batch
    from tests.test_runs import ScriptedClient, _install

    left = _content(1, "", "standard")
    right = _content(2, "", "standard")
    _install(monkeypatch, ScriptedClient(gen_payload=[left, right]))
    batch = make_batch(client, count=2, mode="standard")
    assert generate(client, batch["id"])["status"] == "succeeded"
    tasks = client.get("/api/v1/tasks", params={"batch_id": batch["id"]}).json()["items"]
    first = next(item for item in tasks if item["name"] == left["name"])
    second = next(item for item in tasks if item["name"] == right["name"])
    before = client.get(f"/api/v1/tasks/{second['id']}").json()
    saved = client.post(
        f"/api/v1/tasks/{second['id']}/versions",
        json={"expected_revision": before["summary"]["revision"], "content": left},
        headers={"Idempotency-Key": "make-duplicate"},
    )
    assert saved.status_code == 201
    current = client.get(f"/api/v1/tasks/{first['id']}").json()
    assert current["summary"]["batch_comparison"] == "duplicate"
    decision = client.post(
        f"/api/v1/tasks/{first['id']}/decisions",
        json={"expected_revision": current["summary"]["revision"],
              "version_id": current["current_version"]["id"], "decision": "approve"},
        headers={"Idempotency-Key": "check-current-batch"},
    )
    assert decision.status_code == 422
    assert decision.json()["error"]["code"] == "RULE_GATE_FAILED"
