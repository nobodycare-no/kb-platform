"""FastAPI 应用工厂。

服务边界（见 docs/sad/SAD.md）：backend 不直接调用任何模型 API，
模型访问一律收敛在 ai-service。
"""
from fastapi import FastAPI

from app.api import health


def create_app() -> FastAPI:
    app = FastAPI(
        title="kb-platform backend",
        version="0.1.0",
        description="企业级知识库管理平台 - 主后端",
    )
    app.include_router(health.router)
    return app


app = create_app()
