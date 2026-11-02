"""批次 1B：health/settings 与附件解析。"""
from __future__ import annotations

import io

from openpyxl import Workbook

from tests.conftest import LOCAL


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body == {"status": "ok", "database": "ok", "contract_version": "0.2.0"}
    assert r.headers.get("x-request-id", "").startswith("req_")


def test_settings_default_and_update(client):
    r = client.get("/api/v1/settings")
    assert r.status_code == 200
    assert r.json()["api_key_set"] is False

    r = client.put(
        "/api/v1/settings",
        json={
            "base_url": "http://127.0.0.1:9000/v1",
            "generation_model": "gen-m",
            "review_model": "rev-m",
            "api_key": "sk-demo",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["api_key_set"] is True
    assert "api_key" not in body  # 密钥不回显

    r = client.get("/api/v1/settings")
    assert r.json() == {
        "api_format": "openai",
        "base_url": "http://127.0.0.1:9000/v1",
        "generation_model": "gen-m",
        "review_model": "rev-m",
        "api_key_set": True,
    }


def test_anthropic_settings_and_legacy_update(client):
    payload = {'base_url': 'https://model.local/v1/messages', 'generation_model': 'claude-test',
               'api_format': 'anthropic', 'api_key': 'test'}
    result = client.put('/api/v1/settings', json=payload)
    assert result.status_code == 200
    assert result.json()['api_format'] == 'anthropic'
    result = client.put('/api/v1/settings', json={
        'base_url': 'https://model.local/v1', 'generation_model': 'new-model',
    })
    assert result.json()['api_format'] == 'anthropic'
    assert result.json()['api_key_set']
    assert client.put('/api/v1/settings', json={**payload, 'api_format': 'invalid'}).status_code == 422


def test_settings_uses_generation_model_for_review_by_default(client):
    r = client.put(
        "/api/v1/settings",
        json={
            "base_url": "https://api.example.com/v1",
            "generation_model": "one-model",
            "api_key": "sk-demo",
        },
    )
    assert r.status_code == 200
    assert r.json()["review_model"] == "one-model"


def test_settings_validation(client):
    # 空密钥拒绝
    r = client.put(
        "/api/v1/settings",
        json={
            "base_url": "https://api.example.com/v1",
            "generation_model": "g",
            "review_model": "r",
            "api_key": "",
        },
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"

    # 带用户信息的 URL 拒绝
    r = client.put(
        "/api/v1/settings",
        json={
            "base_url": "https://user:pass@api.example.com/v1",
            "generation_model": "g",
            "review_model": "r",
        },
    )
    assert r.status_code == 422

    # 缺字段 / 未知字段拒绝
    r = client.put("/api/v1/settings", json={"base_url": "https://x/v1"})
    assert r.status_code == 422
    r = client.put(
        "/api/v1/settings",
        json={"base_url": "https://x/v1", "generation_model": "g", "review_model": "r", "extra": 1},
    )
    assert r.status_code == 422

    # 省略 api_key 保留原密钥
    client.put(
        "/api/v1/settings",
        json={"base_url": "https://x/v1", "generation_model": "g", "review_model": "r", "api_key": "sk-1"},
    )
    r = client.put(
        "/api/v1/settings",
        json={"base_url": "https://x/v1", "generation_model": "g2", "review_model": "r2"},
    )
    assert r.json()["api_key_set"] is True


def test_settings_busy_rejected(client):
    from app import db

    with db.tx() as conn:
        conn.execute(
            "INSERT INTO runs (id, batch_id, task_id, task_ids_json, kind, stage, status,"
            " progress_total, progress_completed, progress_failed, created_at)"
            " VALUES ('run_x','batch_x',NULL,'[]','generate_batch','generating','running',1,0,0,?)",
            (db.utcnow(),),
        )
    r = client.put(
        "/api/v1/settings",
        json={"base_url": "https://x/v1", "generation_model": "g", "review_model": "r"},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "RUN_BUSY"


def _xlsx_file(rows: list[list[str]], sheet: str = "Sheet1") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_upload_txt_and_query(client):
    r = client.post(
        "/api/v1/attachments",
        files={"file": ("物料.txt", "收纳篮、毛巾".encode("utf-8"), "text/plain")},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["parsed_text"] == "收纳篮、毛巾"
    assert body["text_length"] == len("收纳篮、毛巾")
    att_id = body["id"]

    r = client.get("/api/v1/attachments")
    assert r.status_code == 200 and r.json()["total"] == 1
    summary = r.json()["items"][0]
    assert "parsed_text" not in summary  # 列表只给摘要

    r = client.get(f"/api/v1/attachments/{att_id}")
    assert r.json()["parsed_text"] == "收纳篮、毛巾"

    r = client.get("/api/v1/attachments/att_missing")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


def test_upload_csv_gbk_and_xlsx(client):
    gbk = "名称,数量\n收纳篮,1".encode("gbk")
    r = client.post("/api/v1/attachments", files={"file": ("库存.csv", gbk, "text/csv")})
    assert r.status_code == 201
    assert "收纳篮 | 1" in r.json()["parsed_text"]

    xlsx = _xlsx_file([["名称", "数量"], ["毛巾", "2"]], sheet="库存")
    r = client.post(
        "/api/v1/attachments",
        files={"file": ("库存.xlsx", xlsx, "application/vnd...")},
    )
    assert r.status_code == 201
    text = r.json()["parsed_text"]
    assert "## 工作表：库存" in text and "毛巾 | 2" in text


def test_upload_rejections(client):
    # 非本地 Host
    r = client.post(
        "/api/v1/attachments",
        files={"file": ("a.txt", b"x", "text/plain")},
        headers={"host": "evil.example.com"},
    )
    assert r.status_code == 403

    # 不支持的扩展名
    r = client.post(
        "/api/v1/attachments",
        files={"file": ("a.pdf", b"%PDF", "application/pdf")},
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_FILE"

    # 坏 XLSX
    r = client.post(
        "/api/v1/attachments", files={"file": ("a.xlsx", b"not a zip", "application/vnd...")}
    )
    assert r.status_code == 400

    # XLSX 公式单元格
    xlsx = _xlsx_file([["a"], ["=SUM(1,2)"]])
    r = client.post(
        "/api/v1/attachments", files={"file": ("a.xlsx", xlsx, "application/vnd...")}
    )
    assert r.status_code == 400 and "公式" in r.json()["error"]["message"]

    # 超过 5MiB
    big = b"x" * (5 * 1024 * 1024 + 1)
    r = client.post("/api/v1/attachments", files={"file": ("a.txt", big, "text/plain")})
    assert r.status_code == 413 and r.json()["error"]["code"] == "FILE_TOO_LARGE"

    # 解析文本超过 50k 字符
    long_text = "x" * 50_001
    r = client.post(
        "/api/v1/attachments", files={"file": ("a.txt", long_text.encode(), "text/plain")}
    )
    assert r.status_code == 413 and r.json()["error"]["code"] == "CONTEXT_TOO_LARGE"

    # CSV 单元格超过 20000
    many = "\n".join(",".join(["a", "b"]) for _ in range(10_500))
    r = client.post(
        "/api/v1/attachments", files={"file": ("a.csv", many.encode(), "text/csv")}
    )
    assert r.status_code == 413
