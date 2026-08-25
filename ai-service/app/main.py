"""ai-service 入口：健康自检 + 内部端点（X-Internal-Token 保护）。

服务边界（SAD §3）：本服务不持有 MySQL 连接；权限判断回调 backend。
"""
from contextlib import asynccontextmanager
from typing import AsyncIterator

import hmac
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.gateway.model_gateway import ModelGateway


def create_app(gateway: ModelGateway | None = None, settings: Settings | None = None) -> FastAPI:
    gw = gateway or ModelGateway(settings or get_settings())

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await gw.aclose()

    app = FastAPI(title="kb-platform ai-service", version="0.1.0", lifespan=lifespan)
    app.state.gateway = gw

    def verify_internal(x_internal_token: str = Header(default="")) -> None:
        if not hmac.compare_digest(x_internal_token, gw.settings.internal_token):
            raise HTTPException(status_code=401, detail="invalid internal token")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/health/models")
    async def health_models() -> dict:
        """FR-G01：LLM / embedding / reranker 三依赖连通性自检（2s 探测超时）。"""
        return await gw.health()

    class EmbedRequest(BaseModel):
        texts: list[str]

    @app.post("/internal/embed")
    async def embed(req: EmbedRequest, _: None = Depends(verify_internal)) -> dict:
        vectors = await gw.embed(req.texts)
        return {"vectors": vectors, "dim": len(vectors[0]) if vectors else 0}

    return app


app = create_app()
