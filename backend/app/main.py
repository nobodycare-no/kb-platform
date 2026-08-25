"""FastAPI 应用工厂。

服务边界（见 docs/sad/SAD.md）：backend 不直接调用任何模型 API，
模型访问一律收敛在 ai-service。
"""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import ai, auth, health, knowledge, org
from app.internal import routes as internal_routes
from app.core.errors import ApiError
from app.core.responses import err


def create_app() -> FastAPI:
    app = FastAPI(
        title="kb-platform backend",
        version="0.2.0",
        description="企业级知识库管理平台 - 主后端",
    )

    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status_code, content=err(exc.code, exc.message, exc.data))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content=err(4400, "参数校验失败", exc.errors()))

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(org.router)
    app.include_router(knowledge.router)
    app.include_router(ai.router)
    app.include_router(internal_routes.router)
    return app


app = create_app()
