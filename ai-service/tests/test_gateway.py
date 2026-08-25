"""ModelGateway 单测：全部经 httpx.MockTransport 注入假端点（无真实 GPU 依赖）。"""
import json

import httpx
import pytest

from app.core.config import Settings
from app.gateway.model_gateway import ModelGateway, ModelUnavailable


def make_settings(**kw) -> Settings:
    base = dict(
        internal_token="t",
        milvus_uri="milvus:19530",
        llm_base_url="http://llm-primary:6006/v1",
        llm_api_key="sk-primary",
        llm_model="qwen3-8b",
        llm_fallback_base_url="http://llm-fallback:6006/v1",
        llm_fallback_api_key="sk-fallback",
        llm_fallback_model="gpt-5.6-luna",
        llm_fail_switch=1,
        embedding_base_url="http://bge:6008",
        embedding_protocol="autodl_bge",
        embed_dim=4,
        rerank_url="http://bge:6008/v1/rerank",
        rerank_health_url="http://bge:6008/health",
        rerank_protocol="custom",
    )
    base.update(kw)
    return Settings(**base)


def sse_bytes(contents: list[str]) -> bytes:
    lines = ["data: " + json.dumps({"choices": [{"delta": {"content": c}}]}) for c in contents]
    lines.append("data: [DONE]")
    return ("\n\n".join(lines) + "\n\n").encode()


async def collect(aiter) -> str:
    return "".join([chunk async for chunk in aiter])


# ---------- Embedding ----------

async def test_embed_autodl_bge_parses_dense():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "bge"
        body = json.loads(request.content)
        assert body == {"embedding_documents": ["a", "b"]}
        return httpx.Response(200, json={"dense": [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]], "sparse": []})

    gw = ModelGateway(make_settings(), transport=httpx.MockTransport(handler))
    vectors = await gw.embed(["a", "b"])
    assert len(vectors) == 2 and vectors[1] == [0.5, 0.6, 0.7, 0.8]


async def test_embed_openai_sorted_by_index():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/embeddings")
        assert request.headers["Authorization"] == "Bearer sk-emb"
        return httpx.Response(200, json={"data": [
            {"index": 1, "embedding": [0.4, 0.3, 0.2, 0.1]},
            {"index": 0, "embedding": [0.1, 0.2, 0.3, 0.4]},
        ]})

    s = make_settings(embedding_protocol="openai", embedding_api_key="sk-emb")
    gw = ModelGateway(s, transport=httpx.MockTransport(handler))
    vectors = await gw.embed(["first", "second"])
    assert vectors[0][0] == 0.1 and vectors[1][0] == 0.4


async def test_embed_non200_raises_unavailable():
    gw = ModelGateway(make_settings(), transport=httpx.MockTransport(
        lambda req: httpx.Response(503, text="model loading")))
    with pytest.raises(ModelUnavailable, match="503"):
        await gw.embed(["x"])


async def test_embed_empty_input_short_circuits():
    gw = ModelGateway(make_settings(), transport=httpx.MockTransport(
        lambda req: httpx.Response(500)))
    assert await gw.embed([]) == []


async def test_embed_dimension_mismatch_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"dense": [[0.1, 0.2]]})
    gw = ModelGateway(make_settings(embed_dim=4), transport=httpx.MockTransport(handler))
    with pytest.raises(ModelUnavailable, match="维度"):
        await gw.embed(["x"])


# ---------- Rerank ----------

async def test_rerank_custom_scores_in_input_order():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["query"] == "差旅标准" and body["documents"] == ["d1", "d2"]
        return httpx.Response(200, json={"scores": [0.91, 0.13]})
    gw = ModelGateway(make_settings(), transport=httpx.MockTransport(handler))
    assert await gw.rerank("差旅标准", ["d1", "d2"]) == [0.91, 0.13]


async def test_rerank_tei_aligns_by_index():
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["texts"] == ["d1", "d2"]
        return httpx.Response(200, json=[{"index": 1, "score": 0.95}, {"index": 0, "score": 0.20}])
    gw = ModelGateway(make_settings(rerank_protocol="tei"), transport=httpx.MockTransport(handler))
    scores = await gw.rerank("q", ["d1", "d2"])
    assert scores == [0.20, 0.95]


# ---------- LLM 流式 + 主备切换 ----------

async def test_chat_stream_primary_success_resets_counter():
    calls = {"primary": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "llm-primary":
            calls["primary"] += 1
            return httpx.Response(200, content=sse_bytes(["你好", "，世界"]), headers={"content-type": "text/event-stream"})
        return httpx.Response(500)

    gw = ModelGateway(make_settings(llm_fail_switch=2), transport=httpx.MockTransport(handler))
    out = await collect(gw.chat_stream([{"role": "user", "content": "hi"}]))
    assert out == "你好，世界"
    assert calls["primary"] == 1
    assert gw._using_fallback is False


async def test_failover_sticky_after_threshold():
    calls = {"primary": 0, "fallback": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "llm-primary":
            calls["primary"] += 1
            return httpx.Response(500, text="boom")
        calls["fallback"] += 1
        return httpx.Response(200, content=sse_bytes(["来自备用"]), headers={"content-type": "text/event-stream"})

    gw = ModelGateway(make_settings(llm_fail_switch=1), transport=httpx.MockTransport(handler))

    first = await collect(gw.chat_stream([{"role": "user", "content": "1"}]))
    assert first == "来自备用"
    assert gw._using_fallback is True

    _ = await collect(gw.chat_stream([{"role": "user", "content": "2"}]))
    # 粘性：第二次直接走 fallback，不再打主端点
    assert calls == {"primary": 1, "fallback": 2}


async def test_no_fallback_configured_raises():
    gw = ModelGateway(
        make_settings(llm_fail_switch=1, llm_fallback_base_url="", llm_fallback_api_key="", llm_fallback_model=""),
        transport=httpx.MockTransport(lambda req: httpx.Response(500)),
    )
    with pytest.raises(ModelUnavailable):
        async for _ in gw.chat_stream([{"role": "user", "content": "hi"}]):
            pass


# ---------- 健康自检 ----------

async def test_health_reports_each_dependency():
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "llm-primary":
            return httpx.Response(200, json={"data": []})
        if host == "bge":
            return httpx.Response(200)          # embedding /health 正常
        if host == "rr":
            return httpx.Response(404)          # reranker 健康端点模拟宕机
        return httpx.Response(500)

    gw = ModelGateway(
        make_settings(rerank_health_url="http://rr:6008/health"),
        transport=httpx.MockTransport(handler),
    )
    report = await gw.health()
    assert report["llm"]["ok"] is True and "qwen3-8b" in report["llm"]["provider"]
    assert report["embedding"]["ok"] is True
    assert report["reranker"]["ok"] is False and "404" in report["reranker"]["detail"]
