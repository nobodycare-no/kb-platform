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

    app = FastAPI(title="kb-platform ai-service", version="0.2.0", lifespan=lifespan)
    app.state.gateway = gw
    app.state.milvus = None

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

    # ---------- 知识索引（Milvus 唯一入口，SAD §2）----------

    def _store():
        from app.gateway.milvus_store import MilvusStore
        if app.state.milvus is None:
            app.state.milvus = MilvusStore(uri=gw.settings.milvus_uri, dim=gw.settings.embed_dim)
            app.state.milvus.ensure_collections()
        return app.state.milvus

    class KbIndexRequest(BaseModel):
        unit_id: int
        chunks: list[dict]   # [{seq:int, text:str}]

    @app.post("/internal/kb/index")
    async def kb_index(req: KbIndexRequest, _: None = Depends(verify_internal)) -> dict:
        try:
            store = _store()
        except Exception as e:  # Milvus 不可达
            raise HTTPException(status_code=503, detail=f"milvus unavailable: {e}") from e
        texts = [c["text"] for c in req.chunks]
        vectors = await gw.embed(texts) if texts else []
        items = [(int(c["seq"]), c["text"]) for c in req.chunks]
        store.replace_chunks(req.unit_id, items, vectors)
        return {"indexed": len(items)}

    @app.delete("/internal/kb/unit/{unit_id}")
    async def kb_delete(unit_id: int, _: None = Depends(verify_internal)) -> dict:
        try:
            store = _store()
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"milvus unavailable: {e}") from e
        store.delete_unit(unit_id)
        return {"deleted": unit_id}

    return app


app = create_app()
