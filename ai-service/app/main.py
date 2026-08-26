"""ai-service 入口：健康自检 + 内部端点（X-Internal-Token 保护）。

服务边界（SAD §3）：本服务不持有 MySQL 连接；权限判断回调 backend。
"""
from contextlib import asynccontextmanager
from typing import AsyncIterator

import hmac
import json
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.gateway.model_gateway import ModelGateway, ModelUnavailable


def create_app(gateway: ModelGateway | None = None, settings: Settings | None = None,
               chain_ctx=None) -> FastAPI:
    gw = gateway or ModelGateway(settings or get_settings())

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await gw.aclose()

    app = FastAPI(title="kb-platform ai-service", version="0.2.0", lifespan=lifespan)
    app.state.gateway = gw
    app.state.milvus = None
    app.state.chain_ctx = chain_ctx   # 允许测试/部署方注入预构建上下文

    def verify_internal(x_internal_token: str = Header(default="")) -> None:
        if not hmac.compare_digest(x_internal_token, gw.settings.internal_token):
            raise HTTPException(status_code=401, detail="invalid internal token")

    @app.exception_handler(ModelUnavailable)
    async def model_unavailable_handler(_: Request, exc: ModelUnavailable):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=503,
                            content={"code": 4503, "message": f"模型服务不可用: {exc}", "data": None})

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
            app.state.milvus = MilvusStore(
                uri=gw.settings.milvus_uri, dim=gw.settings.embed_dim,
                kb_collection=gw.settings.milvus_kb_collection,
                faq_collection=gw.settings.milvus_faq_collection,
            )
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

    class FaqUpsertRequest(BaseModel):
        faq_id: int
        question: str

    @app.post("/internal/faq/upsert")
    async def faq_upsert(req: FaqUpsertRequest, _: None = Depends(verify_internal)) -> dict:
        """FAQ 发布时写语义缓存（L2）。"""
        store = _store()
        vector = await gw.embed([req.question])
        store.upsert_faq(req.faq_id, req.question, vector[0])
        return {"upserted": req.faq_id}

    # ---------- 鉴权 RAG 流式问答（SDD §4.1）----------

    def _chain_ctx():
        from app.chain.auth_rag import ChainContext
        from app.retrieval.faq_cache import FaqCacheService

        if app.state.chain_ctx is None:
            sync_redis = None
            try:
                import redis as redis_sync

                sync_redis = redis_sync.Redis.from_url(
                    gw.settings.redis_url,
                    decode_responses=True, socket_connect_timeout=1, socket_timeout=2)
                sync_redis.ping()
            except Exception:
                sync_redis = None

            async def fetch_faq_answer(faq_id: int) -> dict | None:
                client = gw._http()
                try:
                    resp = await client.get(
                        f"{gw.settings.backend_base_url}/internal/faq/{faq_id}",
                        headers={"X-Internal-Token": gw.settings.internal_token},
                        timeout=3,
                    )
                    if resp.status_code == 200:
                        return resp.json()
                except Exception:
                    pass
                return None

            faq_cache = FaqCacheService(
                gateway=gw,
                store=_store(),
                redis_client=sync_redis,    # L1 精确缓存（FR-F03 / FR-C04 同源）
                faq_answer_fetcher=fetch_faq_answer,
                exact_sim=gw.settings.faq_exact_sim,
            )
            app.state.chain_ctx = ChainContext(
                gateway=gw,
                store_provider=_store,
                faq_cache=faq_cache,
                backend_base_url=gw.settings.backend_base_url,
                internal_token=gw.settings.internal_token,
                dense_top_k=gw.settings.dense_top_k,
                keyword_top_k=gw.settings.keyword_top_k,
                keyword_timeout_ms=gw.settings.keyword_timeout_ms,
                rrf_k=gw.settings.rrf_k,
                rerank_top_n=gw.settings.rerank_top_n,
            )
        return app.state.chain_ctx

    class RagStreamRequest(BaseModel):
        user_id: int
        department_id: int | None = None
        is_super: bool = False
        session_id: int | None = None
        question: str

    @app.post("/internal/rag/stream", dependencies=[Depends(verify_internal)])
    async def rag_stream(req: RagStreamRequest) -> StreamingResponse:
        from app.chain.auth_rag import run_stream

        ctx = _chain_ctx()

        async def event_gen() -> AsyncIterator[bytes]:
            try:
                async for event, data in run_stream(ctx, **req.model_dump()):
                    yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")
            except Exception as e:  # 兜底：任何未预期异常转为 error 事件
                yield f"event: error\ndata: {json.dumps({'message': str(e)[:200]}, ensure_ascii=False)}\n\n".encode("utf-8")

        return StreamingResponse(event_gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    return app


app = create_app()
