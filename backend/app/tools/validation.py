"""规则校验适配器：包装 skills/snapshot 里的 validate_tasks 与 materials。

只做包装与结果映射，不复制规则逻辑；工具异常返回 RULE_TOOL_FAILED 类错误，
绝不伪造 passed。
"""
from __future__ import annotations

import json
import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import CONFIG
from ..errors import ApiError
from ..prompts_spec import STEP_RANGES

_lock = threading.Lock()
_loaded = False

_STEP_NO_RE = re.compile(r"第(\d+)步")
_RULE_ID_RE = re.compile(r"(L-\d{3})")


def _import_snapshot() -> None:
    global _loaded
    with _lock:
        if _loaded:
            return
        scripts = str(Path(CONFIG.skill_snapshot_dir) / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        import materials  # noqa: F401
        import validate_tasks  # noqa: F401

        _loaded = True


def rule_snapshot_id() -> str:
    manifest = Path(CONFIG.skill_snapshot_dir) / "MANIFEST.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    return data["rule_snapshot_id"]


def steps_to_text(steps: list[str]) -> str:
    """契约中的 steps 是不带编号数组；校验脚本要求 1.xxx 编号行。"""
    return "\n".join(f"{i + 1}.{s}" for i, s in enumerate(steps))


def materials_to_text(materials: list[dict[str, Any]]) -> str:
    import materials as m

    return m.format_materials([(item["name"], item["quantity"]) for item in materials])


class RuleToolFailure(Exception):
    pass


def validate_content(
    content: dict[str, Any], task_mode: str, snapshot_id: str
) -> dict[str, Any]:
    """返回 ValidationReport dict。领域失败 → status=failed（允许保存）；工具崩溃 → 抛 ApiError。"""
    try:
        _import_snapshot()
        import materials as materials_mod
        import validate_tasks as vt

        steps_text = steps_to_text(content["steps"])
        row = {"任务名称": content["name"], "任务步骤": steps_text}
        lo, hi = STEP_RANGES[task_mode]
        raw_issues, _fingerprint, _skills = vt.validate_row(row, lo, hi, [])

        issues: list[dict[str, Any]] = []
        for level, message in raw_issues:
            step_match = _STEP_NO_RE.search(message)
            rule_match = _RULE_ID_RE.search(message)
            issues.append(
                {
                    "code": "RULE_VIOLATION" if level == "BLOCK" else "RULE_WARNING",
                    "severity": "error" if level == "BLOCK" else "warning",
                    "message": message,
                    "step_no": int(step_match.group(1)) if step_match else None,
                    "rule_id": rule_match.group(1) if rule_match else None,
                }
            )

        # 物料一致性：步骤推导 vs 正文登记，不一致按 error 提示，不静默改正文
        listed = materials_to_text(content["materials"])
        for message in materials_mod.compare_materials(steps_text, listed):
            issues.append(
                {
                    "code": "MATERIALS_MISMATCH",
                    "severity": "error",
                    "message": message,
                    "step_no": None,
                    "rule_id": None,
                }
            )

        status = "failed" if any(i["severity"] == "error" for i in issues) else "passed"
        return {
            "status": status,
            "issues": issues,
            "checked_at": datetime.now(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
            "rule_snapshot_id": snapshot_id,
        }
    except ApiError:
        raise
    except Exception as exc:  # 快照脚本内部异常 → 技术错误，不允许伪造通过
        raise ApiError(
            500,
            "RULE_TOOL_FAILED",
            "规则校验工具执行失败，本次结果不可用",
            {"tool_error": type(exc).__name__},
        ) from exc
