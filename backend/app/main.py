"""FastAPI 应用工厂：异常适配、请求 ID、启动恢复、Worker、前端托管。"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import db, ids
from .api import routers
from .config import CONFIG
from .errors import ApiError
from .instance_lock import lock_data_dir
from .services import runs as runs_service

logger = logging.getLogger("g2tasks")


def error_response(
    request: Request | None, status_code: int, code: str, message: str, details: dict | None = None
) -> JSONResponse:
    request_id = getattr(getattr(request, "state", None), "request_id", "") if request else ""
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "request_id": request_id or ids.new_request_id(),
            }
        },
    )


def create_app() -> FastAPI:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        with lock_data_dir(CONFIG.data_dir):
            db.init_db()
            recovered = runs_service.recover_interrupted()
            if any(recovered.values()):
                logger.info("startup recovery: %s", recovered)
            runs_service.start_worker(_app)
            try:
                yield
            finally:
                runs_service.stop_worker()

    app = FastAPI(
        title="G2 Task System Demo API",
        version="0.1.0",
        docs_url="/api/docs",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = ids.new_request_id()
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        return response

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError):
        return error_response(request, exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        fields = sorted(
            {
                ".".join(str(p) for p in err["loc"][1:])
                for err in exc.errors()
                if err.get("loc")
            }
        )
        return error_response(
            request,
            422,
            "VALIDATION_ERROR",
            "请求字段校验失败",
            {"fields": fields},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        code = {404: "NOT_FOUND", 405: "NOT_FOUND", 413: "FILE_TOO_LARGE", 415: "VALIDATION_ERROR"}.get(
            exc.status_code, "INTERNAL_ERROR" if exc.status_code >= 500 else "INVALID_STATE"
        )
        return error_response(request, exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        logger.exception("unhandled error", exc_info=exc)
        return error_response(request, 500, "INTERNAL_ERROR", "服务内部错误")

    app.include_router(routers.router)

    # 交付模式：FastAPI 托管前端构建产物（存在时）
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.exists():
        from fastapi.staticfiles import StaticFiles

        app.mount(
            "/assets",
            StaticFiles(directory=dist / "assets"),
            name="frontend-assets",
        )

        @app.get("/", include_in_schema=False)
        async def index():
            from fastapi.responses import FileResponse

            return FileResponse(dist / "index.html")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            from fastapi.responses import FileResponse

            # API 前缀不允许被 SPA fallback 吞掉：未匹配的 API 路径按 404 JSON 返回
            if full_path == "api" or full_path.startswith("api/"):
                return error_response(
                    request=None, status_code=404, code="NOT_FOUND", message="接口不存在"
                )
            candidate = dist / full_path
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
