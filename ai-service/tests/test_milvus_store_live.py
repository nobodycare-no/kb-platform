"""MilvusStore 真实往返测试（连本地 compose 的 milvus，回环端口）。

不可达时自动 skip；使用独立 *_test 集合并在结束时清理。
注意：本机代理(http_proxy)会劫持 gRPC 回环连接，必须设置 NO_PROXY。
"""
import os

os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")

import pytest

from app.gateway.milvus_store import MilvusStore

URI = "http://127.0.0.1:19530"
DIM = 8


def _e(*positions: int) -> list[float]:
    """单位基向量：仅在给定下标处为 1。不同 positions 之间余弦相似度为 0。"""
    v = [0.0] * DIM
    for i in positions:
        v[i] = 1.0
    return v


@pytest.fixture(scope="module")
def store() -> MilvusStore:
    try:
        probe = MilvusClient(uri=URI)
        probe.list_collections()
    except Exception as e:  # pragma: no cover - 环境相关
        pytest.skip(f"Milvus 不可达({URI}): {e}")
    store = MilvusStore(uri=URI, dim=DIM,
                        kb_collection="kb_chunks_test", faq_collection="faq_vectors_test")
    store.reset()
    yield store
    store.reset()


from pymilvus import MilvusClient  # noqa: E402  （放底部避免 skip 前强依赖）


async def test_ensure_collections_idempotent(store: MilvusStore):
    store.ensure_collections()
    store.ensure_collections()
    assert store.client.has_collection(store.kb_collection)
    assert store.client.has_collection(store.faq_collection)


async def test_replace_and_dense_search_roundtrip(store: MilvusStore):
    items = [(0, "差旅住宿标准条款"), (1, "报销流程说明"), (2, "薪酬保密制度")]
    vectors = [_e(0), _e(1), _e(2)]
    store.replace_chunks(unit_id=101, items=items, vectors=vectors)

    assert store.count_chunks_for_unit(101) == 3

    hits = store.search_dense(_e(0), top_k=2)
    assert len(hits) >= 1
    best = hits[0]
    assert best.unit_id == 101 and best.seq == 0
    assert "差旅住宿标准" in best.content
    # 分数按相关性降序
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)


async def test_delete_unit_removes_all_chunks(store: MilvusStore):
    store.replace_chunks(unit_id=102, items=[(0, "临时数据")], vectors=[_e(5)])
    assert store.count_chunks_for_unit(102) == 1
    store.delete_unit(102)
    assert store.count_chunks_for_unit(102) == 0


async def test_faq_upsert_and_threshold(store: MilvusStore):
    store.upsert_faq(faq_id=9001, question="发票丢了怎么报销？", vector=_e(3))

    faq_id, score = store.search_faq(_e(3), threshold=0.92)
    assert faq_id == 9001 and score >= 0.92

    # 正交方向 → 相似度≈0，低于阈值不命中
    faq_id2, score2 = store.search_faq(_e(4), threshold=0.92)
    assert faq_id2 is None and score2 < 0.92


async def test_replace_same_unit_twice_no_duplicates(store: MilvusStore):
    items = [(i, f"内容{i}") for i in range(3)]
    vecs = [_e(6)] * 3
    store.replace_chunks(unit_id=103, items=items, vectors=vecs)
    store.replace_chunks(unit_id=103, items=items, vectors=vecs)
    assert store.count_chunks_for_unit(103) == 3


# ---------- 内部索引端点全链路（embed stub + 真实 Milvus）----------

async def test_internal_kb_index_end_to_end():
    import json

    import httpx
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.gateway.model_gateway import ModelGateway
    from app.main import create_app

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        docs = body["embedding_documents"]
        vecs = [[1.0 if i == (ord(d[0]) % DIM) else 0.0 for i in range(DIM)] for d in docs]
        return httpx.Response(200, json={"dense": vecs, "sparse": []})

    settings = Settings(
        internal_token="t", milvus_uri=URI, embed_dim=DIM,
        milvus_kb_collection="kb_chunks_idx_e2e",
        milvus_faq_collection="faq_vectors_idx_e2e",
        llm_base_url="", embedding_base_url="http://bge-stub",
        embedding_protocol="autodl_bge", rerank_url="", rerank_health_url="",
    )
    app = create_app(ModelGateway(settings, transport=httpx.MockTransport(handler)))
    client = TestClient(app)
    headers = {"X-Internal-Token": "t"}

    resp = client.post("/internal/kb/index",
                       json={"unit_id": 777, "chunks": [
                           {"seq": 0, "text": "甲文档"}, {"seq": 1, "text": "乙文档"}]},
                       headers=headers)
    assert resp.status_code == 200 and resp.json()["indexed"] == 2

    store = app.state.milvus
    assert store.count_chunks_for_unit(777) == 2

    # 未带令牌 → 401
    assert client.post("/internal/kb/index", json={"unit_id": 1, "chunks": []}).status_code == 401

    deleted = client.delete("/internal/kb/unit/777", headers=headers)
    assert deleted.status_code == 200
    assert store.count_chunks_for_unit(777) == 0
