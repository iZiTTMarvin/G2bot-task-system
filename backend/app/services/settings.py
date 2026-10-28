"""模型设置：data/config/settings.json 保存，接口只回 api_key_set。"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit

from .. import db
from ..config import CONFIG
from ..errors import ApiError, validation_error

DEFAULTS: dict[str, Any] = {
    "base_url": "https://api.openai.com/v1",
    "generation_model": "",
    "review_model": "",
    "api_key": "",
}


def _load() -> dict[str, Any]:
    if not CONFIG.settings_file.exists():
        return dict(DEFAULTS)
    data = json.loads(CONFIG.settings_file.read_text(encoding="utf-8"))
    merged = dict(DEFAULTS)
    merged.update({k: data.get(k, DEFAULTS[k]) for k in DEFAULTS})
    return merged


def get_settings() -> dict[str, Any]:
    s = _load()
    return {
        "base_url": s["base_url"],
        "generation_model": s["generation_model"],
        "review_model": s["review_model"],
        "api_key_set": bool(s["api_key"]),
    }


def _validate_base_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise validation_error("base_url 必须是 http/https 地址", ["base_url"])
    if not parts.netloc:
        raise validation_error("base_url 缺少主机名", ["base_url"])
    if parts.username or parts.password or parts.query or parts.fragment:
        raise validation_error(
            "base_url 不能包含用户名、密码、query 或 fragment", ["base_url"]
        )
    return url


def update_settings(payload: dict[str, Any]) -> dict[str, Any]:
    """PUT /settings。活动作业时调用方先检查 RUN_BUSY；此处只做格式校验。"""
    for field in ("base_url", "generation_model", "review_model"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise validation_error(f"{field} 不能为空", [field])
    _validate_base_url(payload["base_url"].strip())

    api_key = payload.get("api_key")
    if api_key is not None:
        if not isinstance(api_key, str) or api_key == "":
            raise validation_error("api_key 不允许为空字符串；省略表示保留原密钥", ["api_key"])

    s = _load()
    s["base_url"] = payload["base_url"].strip()
    s["generation_model"] = payload["generation_model"].strip()
    s["review_model"] = payload["review_model"].strip()
    if api_key is not None:
        s["api_key"] = api_key
    CONFIG.config_dir.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.settings_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG.settings_file)
    return get_settings()


def require_model_config() -> None:
    """启动模型作业前的配置闸：422 MODEL_NOT_CONFIGURED。

    演示 Fake 模式（无凭据走通闭环）不要求真实配置；正式通路仍全量检查。
    """
    from ..config import CONFIG

    if CONFIG.demo_fake_model:
        return
    s = _load()
    missing: list[str] = []
    if not s["base_url"]:
        missing.append("base_url")
    if not s["generation_model"]:
        missing.append("generation_model")
    if not s["review_model"]:
        missing.append("review_model")
    if not s["api_key"]:
        missing.append("api_key")
    if missing:
        from ..errors import model_not_configured

        raise model_not_configured(missing)


def raw_config() -> dict[str, Any]:
    """内部使用（Run 配置快照）；不外发密钥。"""
    return _load()


def has_active_run() -> bool:
    row = db.get_conn().execute(
        "SELECT 1 FROM runs WHERE status IN ('queued','running') LIMIT 1"
    ).fetchone()
    return row is not None


EMAIL_RE = re.compile(r"^[^@]+@[^@]+$")  # 预留：防止把密钥误填到模型名等字段
