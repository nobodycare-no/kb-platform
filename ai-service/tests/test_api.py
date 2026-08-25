"""ai-service API 层测试：内部令牌校验 + 健康端点。"""
import httpx
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.gateway.model_gateway import ModelGateway
from app.main import create_app


def make_settings(**kw) -> Settings:
    base = dict(internal_token="secret-token", milvus_uri="m:19530", llm_base_url="")
    base.update(kw)
    return Settings(**base)


def make_client(settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> TestClient:
    app = create_app(ModelGateway(settings, transport=transport))
    return TestClient(app)


def test_health_ok():
    resp = make_client(make_settings()).get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_internal_embed_requires_token():
    client = make_client(make_settings())
    assert client.post("/internal/embed", json={"texts": ["x"]}).status_code == 401


def test_internal_embed_with_token_and_mock_backend():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "bge"
        body = __import__("json").loads(request.content)
        n = len(body["embedding_documents"])
        return httpx.Response(200, json={"dense": [[0.0] * 4 for _ in range(n)], "sparse": []})

    client = make_client(
        make_settings(embedding_base_url="http://bge:6008", embedding_protocol="autodl_bge", embed_dim=4),
        transport=httpx.MockTransport(handler),
    )
    resp = client.post("/internal/embed", json={"texts": ["a", "b"]},
                       headers={"X-Internal-Token": "secret-token"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["dim"] == 4 and len(data["vectors"]) == 2
