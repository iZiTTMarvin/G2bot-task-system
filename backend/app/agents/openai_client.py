"""OpenAI 兼容 HTTP 模型客户端（chat/completions）。

错误分类（契约）：MODEL_TIMEOUT / MODEL_AUTH_ERROR / MODEL_RATE_LIMIT /
MODEL_PROTOCOL_ERROR / MODEL_REQUEST_FAILED。不把认证头或服务商原始响应放进 details。
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from ..errors import ModelCallError
from ..prompts_spec import STEP_RANGES
from ..services import settings as settings_service
from .prompts import generator_prompt, reviewer_prompt

TIMEOUT_SECONDS = 120.0


def _extract_json(text: str) -> Any:
    """从模型输出中提取第一个平衡的 JSON 值；找不到抛协议错误。"""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("[", "]"), ("{", "}")):
        start = text.find(opener)
        if start < 0:
            continue
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    raise ModelCallError(
        "MODEL_PROTOCOL_ERROR", "模型输出不是可解析的 JSON 结构", {"head": text[:120]}
    )


class OpenAIModelClient:
    def __init__(self) -> None:
        cfg = settings_service.raw_config()
        self.base_url: str = cfg["base_url"].rstrip("/")
        self.api_key: str = cfg["api_key"]
        self.generation_model: str = cfg["generation_model"]
        self.review_model: str = cfg["review_model"]

    def _chat(self, *, model: str, system: str, user: str) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.3,
        }
        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
                resp = client.post(
                    url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise ModelCallError("MODEL_TIMEOUT", f"模型请求超时（>{TIMEOUT_SECONDS:.0f}s）") from exc
        except httpx.HTTPError as exc:
            raise ModelCallError(
                "MODEL_REQUEST_FAILED", "模型服务连接失败", {"error_type": type(exc).__name__}
            ) from exc
        if resp.status_code in (401, 403):
            raise ModelCallError("MODEL_AUTH_ERROR", "模型服务认证失败（检查 API Key）")
        if resp.status_code == 429:
            raise ModelCallError("MODEL_RATE_LIMIT", "模型服务限流，请稍后重试")
        if resp.status_code < 200 or resp.status_code >= 300:
            raise ModelCallError(
                "MODEL_REQUEST_FAILED",
                f"模型服务返回 HTTP {resp.status_code}",
                {"status_code": resp.status_code},
            )
        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise KeyError("content")
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ModelCallError(
                "MODEL_PROTOCOL_ERROR", "模型响应缺少 choices[0].message.content"
            ) from exc
        return content

    # ---- 生成 ----

    def generate_batch(
        self, *, goal: str, task_count: int, task_mode: str, reference_text: str
    ) -> list[dict[str, Any]]:
        lo, hi = STEP_RANGES[task_mode]
        user = json.dumps(
            {
                "goal": goal,
                "task_count": task_count,
                "task_mode": task_mode,
                "reference_text": reference_text,
            },
            ensure_ascii=False,
        )
        text = self._chat(
            model=self.generation_model, system=generator_prompt(task_mode, lo, hi), user=user
        )
        data = _extract_json(text)
        if not isinstance(data, list):
            raise ModelCallError("MODEL_PROTOCOL_ERROR", "生成结果不是 JSON 数组")
        tasks = [self._coerce_task(item) for item in data]
        if len(tasks) != task_count:
            raise ModelCallError(
                "MODEL_PROTOCOL_ERROR",
                f"要求生成 {task_count} 条任务，模型返回 {len(tasks)} 条",
                {"expected": task_count, "actual": len(tasks)},
            )
        return tasks

    def revise_task(
        self,
        *,
        goal: str,
        task_mode: str,
        reference_text: str,
        current_content: dict[str, Any],
        feedback: str,
    ) -> dict[str, Any]:
        lo, hi = STEP_RANGES[task_mode]
        user = json.dumps(
            {
                "goal": goal,
                "task_mode": task_mode,
                "reference_text": reference_text,
                "current_task": current_content,
                "human_feedback": feedback,
            },
            ensure_ascii=False,
        )
        text = self._chat(
            model=self.generation_model, system=generator_prompt(task_mode, lo, hi), user=user
        )
        data = _extract_json(text)
        if isinstance(data, list):
            if len(data) != 1:
                raise ModelCallError("MODEL_PROTOCOL_ERROR", "重写应只返回一条任务")
            data = data[0]
        return self._coerce_task(data)

    # ---- 审核 ----

    def review_task(
        self, *, content: dict[str, Any], task_mode: str, reference_text: str
    ) -> dict[str, Any]:
        lo, hi = STEP_RANGES[task_mode]
        user = json.dumps(
            {"task": content, "task_mode": task_mode, "reference_text": reference_text},
            ensure_ascii=False,
        )
        text = self._chat(
            model=self.review_model, system=reviewer_prompt(task_mode, lo, hi), user=user
        )
        data = _extract_json(text)
        return self._coerce_review(data, step_limit=len(content.get("steps", [])))

    # ---- 结构收敛 ----

    @staticmethod
    def _coerce_task(item: Any) -> dict[str, Any]:
        if not isinstance(item, dict):
            raise ModelCallError("MODEL_PROTOCOL_ERROR", "任务条目不是 JSON 对象")
        try:
            name = str(item["name"]).strip()
            steps = [str(s).strip() for s in item["steps"]]
            materials = [
                {"name": str(m["name"]).strip(), "quantity": int(m["quantity"])}
                for m in item["materials"]
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelCallError(
                "MODEL_PROTOCOL_ERROR", "任务缺少 name/steps/materials 或类型不符"
            ) from exc
        if not name or not steps or not materials:
            raise ModelCallError("MODEL_PROTOCOL_ERROR", "任务 name/steps/materials 不能为空")
        return {"name": name, "steps": steps, "materials": materials}

    @staticmethod
    def _coerce_review(data: Any, *, step_limit: int) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ModelCallError("MODEL_PROTOCOL_ERROR", "审核结果不是 JSON 对象")
        verdict = data.get("verdict")
        if verdict not in ("pass", "needs_changes"):
            raise ModelCallError(
                "MODEL_PROTOCOL_ERROR", f"审核 verdict 非法：{verdict!r}"
            )
        issues: list[dict[str, Any]] = []
        for raw in data.get("issues", []) or []:
            if not isinstance(raw, dict):
                raise ModelCallError("MODEL_PROTOCOL_ERROR", "审核 issue 不是对象")
            severity = raw.get("severity")
            step_no = raw.get("step_no")
            if severity not in ("error", "warning"):
                raise ModelCallError("MODEL_PROTOCOL_ERROR", f"issue severity 非法：{severity!r}")
            if step_no is not None:
                if not isinstance(step_no, int) or step_no < 1 or step_no > step_limit:
                    raise ModelCallError(
                        "MODEL_PROTOCOL_ERROR",
                        f"issue step_no 越界：{step_no}（该任务共 {step_limit} 步）",
                    )
            issues.append(
                {
                    "severity": severity,
                    "step_no": step_no,
                    "rule_id": raw.get("rule_id"),
                    "quote": str(raw.get("quote", "") or ""),
                    "message": str(raw.get("message", "") or ""),
                    "suggestion": str(raw.get("suggestion", "") or ""),
                }
            )
        if verdict == "needs_changes" and not issues:
            raise ModelCallError("MODEL_PROTOCOL_ERROR", "needs_changes 必须至少包含一个问题")
        if verdict == "pass" and any(i["severity"] == "error" for i in issues):
            raise ModelCallError("MODEL_PROTOCOL_ERROR", "pass 结论包含 error 级问题")
        return {
            "verdict": verdict,
            "issues": issues,
            "summary": str(data.get("summary", "") or ""),
        }
