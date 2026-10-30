"""沿用设置中的 Provider、地址和模型，交由 LangChain SDK 处理工具协议。"""
from urllib.parse import urlsplit
from functools import cached_property

import anthropic

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from ..services import settings

REQUEST_TIMEOUT = 120.0


class CompatibleAnthropic(ChatAnthropic):
    """保留自定义版本前缀：Anthropic SDK 默认追加 /v1/messages。"""

    def _rewrite_endpoint(self, request):
        # 本系统的 Anthropic 兼容格式沿用 x-api-key，而新版 SDK 默认发送 Bearer。
        request.headers["x-api-key"] = self.anthropic_api_key.get_secret_value()
        if "authorization" in request.headers:
            del request.headers["authorization"]
        path = request.url.path
        prefix = urlsplit(self.anthropic_api_url).path.rstrip("/")
        sdk_prefix = prefix + "/v1/"
        if path.startswith(sdk_prefix):
            request.url = request.url.copy_with(path=prefix + "/" + path[len(sdk_prefix):])

    @cached_property
    def _client(self):
        transport = anthropic.DefaultHttpxClient(
            event_hooks={"request": [self._rewrite_endpoint]}, timeout=REQUEST_TIMEOUT,
        )
        return anthropic.Client(**self._client_params, http_client=transport)

    @cached_property
    def _async_client(self):
        async def rewrite(request):
            self._rewrite_endpoint(request)

        transport = anthropic.DefaultAsyncHttpxClient(
            event_hooks={"request": [rewrite]}, timeout=REQUEST_TIMEOUT,
        )
        return anthropic.AsyncClient(**self._client_params, http_client=transport)


def model_base_url(base_url: str, api_format: str) -> str:
    base = base_url.rstrip("/")
    suffix = "/messages" if api_format == "anthropic" else "/chat/completions"
    if base.endswith(suffix):
        base = base[:-len(suffix)]
    if not urlsplit(base).path:
        base += "/v1"
    return base


def make_model(role: str) -> BaseChatModel:
    cfg = settings.raw_config()
    model = cfg["generation_model" if role == "generator" else "review_model"]
    base = model_base_url(cfg["base_url"], cfg["api_format"])
    if cfg["api_format"] == "anthropic":
        return CompatibleAnthropic(
            model_name=model, api_key=cfg["api_key"], base_url=base,
            temperature=0.3, max_tokens=16384, timeout=REQUEST_TIMEOUT, max_retries=0,
        )
    return ChatOpenAI(
        model=model, api_key=cfg["api_key"], base_url=base,
        temperature=0.3, timeout=REQUEST_TIMEOUT, max_retries=0,
        use_responses_api=False,
    )
