"""ModelGateway —— 全部模型访问的唯一出口（SAD ADR-001 / ADR-006）。

协议矩阵：
- LLM       : OpenAI 兼容 /v1/chat/completions 流式；主端点连续失败 llm_fail_switch 次
              后**粘性**切换备用端点（进程级记忆）；仅在首 delta 前失败才透明切换，
              避免输出重复。
- Embedding : `autodl_bge`（POST {base}/embeddings，body={"embedding_documents":[..]}
              → {"dense":[[..]],"sparse":..}，sparse 忽略）| `openai` 标准格式。
- Rerank    : `custom`＝AutoDL 协议（POST /v1/rerank {query,documents}→{scores}）
              | `tei`（{query,texts}→[{score,index}]），输出均与输入顺序对齐。

可测试性：构造时可注入 httpx.AsyncBaseTransport（MockTransport）。
"""
import json
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import asdict, dataclass

import httpx

from app.core.config import Settings, get_settings


class ModelUnavailable(Exception):
    """模型依赖不可用（网络/非200/解析失败），且无可用的主备切换。"""


@dataclass
class HealthItem:
    ok: bool = False
    latency_ms: int | None = None
    detail: str = ""
    provider: str | None = None


class ModelGateway:
    def __init__(self, settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings or get_settings()
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._llm_fail_count = 0
        self._using_fallback = False

    # ---------- 基础设施 ----------

    def _http(self) -> httpx.AsyncClient:
        # is_closed 防御：跨事件循环/生命周期复用时自动重建
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(transport=self._transport)
        return self._client

    async def aclose(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _llm_provider(self) -> tuple[str, str, str]:
        s = self.settings
        if self._using_fallback:
            return ("fallback", s.llm_fallback_base_url.rstrip("/"), s.llm_fallback_api_key, s.llm_fallback_model)
        return ("primary", s.llm_base_url.rstrip("/"), s.llm_api_key, s.llm_model)

    # ---------- LLM ----------

    async def chat_stream(self, messages: list[dict]) -> AsyncIterator[str]:
        """yield 增量文本；首 delta 前失败自动走主备切换，之后失败抛 ModelUnavailable。"""
        s = self.settings
        tried_primary = self._using_fallback  # 已在 fallback 时不再试 primary

        async def _try(provider_tag: str):
            _, base, key, model = (
                ("primary", s.llm_base_url.rstrip("/"), s.llm_api_key, s.llm_model)
                if provider_tag == "primary"
                else ("fallback", s.llm_fallback_base_url.rstrip("/"), s.llm_fallback_api_key, s.llm_fallback_model)
            )
            if not base:
                raise ModelUnavailable(f"LLM[{provider_tag}] base_url 未配置")
            got_delta = False
            req_timeout = httpx.Timeout(10, read=s.llm_timeout_s, write=30, pool=10)
            async with self._http().stream(
                "POST",
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": model, "messages": messages, "stream": True},
                timeout=req_timeout,
            ) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", "replace")[:300]
                    raise ModelUnavailable(f"LLM[{provider_tag}] HTTP {resp.status_code}: {body}")
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[len("data:"):].strip()
                    if payload == "[DONE]":
                        break
                    obj = json.loads(payload)
                    delta = (obj.get("choices") or [{}])[0].get("delta", {}).get("content")
                    if delta:
                        got_delta = True
                        yield delta
            _ = got_delta  # 供调试；中途断流由上层 except 统一处理

        try:
            async for delta in _try("fallback" if self._using_fallback else "primary"):
                yield delta
            if not self._using_fallback:
                self._llm_fail_count = 0  # 主端点成功即复位计数
            return
        except ModelUnavailable:
            pass

        if not tried_primary and s.llm_fallback_base_url:
            self._llm_fail_count += 1
            if self._llm_fail_count >= s.llm_fail_switch:
                self._using_fallback = True
                async for delta in _try("fallback"):
                    yield delta
                return
        raise ModelUnavailable("LLM 主备端点均不可用")

    # ---------- Embedding ----------

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        s = self.settings
        base = s.embedding_base_url.rstrip("/")
        headers = {}
        payload: dict
        if s.embedding_protocol == "autodl_bge":
            payload = {"embedding_documents": list(texts)}
        else:  # openai
            headers["Authorization"] = f"Bearer {s.embedding_api_key}"
            payload = {"model": s.embedding_model, "input": list(texts)}

        try:
            resp = await self._http().post(
                f"{base}/embeddings", json=payload, headers=headers,
                timeout=httpx.Timeout(5, read=s.embed_timeout_s, write=60),
            )
        except httpx.HTTPError as e:
            raise ModelUnavailable(f"embedding 连接失败: {e}") from e
        if resp.status_code != 200:
            raise ModelUnavailable(f"embedding HTTP {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        if s.embedding_protocol == "autodl_bge":
            vectors = [list(map(float, v)) for v in data.get("dense", [])]
        else:
            items = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
            vectors = [list(map(float, item["embedding"])) for item in items]

        if len(vectors) != len(texts):
            raise ModelUnavailable(f"embedding 返回数量不符: {len(vectors)} != {len(texts)}")
        if vectors and len(vectors[0]) != s.embed_dim:
            raise ModelUnavailable(f"embedding 维度不符: {len(vectors[0])} != {s.embed_dim}")
        return vectors

    # ---------- Rerank ----------

    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        """返回与 documents 等长、顺序对齐的相关性分数。"""
        if not documents:
            return []
        s = self.settings
        try:
            if s.rerank_protocol == "custom":
                resp = await self._http().post(
                    s.rerank_url,
                    json={"query": query, "documents": list(documents)},
                    timeout=httpx.Timeout(5, read=s.rerank_timeout_s, write=30),
                )
            else:  # tei
                resp = await self._http().post(
                    s.rerank_url,
                    json={"query": query, "texts": list(documents)},
                    timeout=httpx.Timeout(5, read=s.rerank_timeout_s, write=30),
                )
        except httpx.HTTPError as e:
            raise ModelUnavailable(f"reranker 连接失败: {e}") from e
        if resp.status_code != 200:
            raise ModelUnavailable(f"reranker HTTP {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        if s.rerank_protocol == "custom":
            scores = [float(x) for x in data["scores"]]
        else:  # tei: 按 index 对齐输入顺序
            aligned = [0.0] * len(documents)
            for item in data:
                aligned[int(item["index"])] = float(item["score"])
            scores = aligned

        if len(scores) != len(documents):
            raise ModelUnavailable(f"reranker 分数数量不符: {len(scores)} != {len(documents)}")
        return scores

    # ---------- 健康自检（FR-G01）----------

    async def _probe(self, method: str, url: str, headers: dict | None = None,
                     timeout_s: float = 2.0) -> HealthItem:
        start = time.perf_counter()
        try:
            resp = await self._http().request(method, url, headers=headers or {},
                                              timeout=httpx.Timeout(timeout_s))
            latency = int((time.perf_counter() - start) * 1000)
            if resp.status_code < 400:
                return HealthItem(ok=True, latency_ms=latency)
            return HealthItem(ok=False, latency_ms=latency, detail=f"HTTP {resp.status_code}")
        except httpx.HTTPError as e:
            return HealthItem(ok=False, latency_ms=None, detail=str(e)[:200])

    async def health(self) -> dict:
        s = self.settings
        tag, base, key, model = self._llm_provider()

        llm = HealthItem(provider=f"{tag}:{model}")
        if base:
            llm = await self._probe("GET", f"{base}/models", {"Authorization": f"Bearer {key}"})
            llm.provider = f"{tag}:{model}"

        emb = HealthItem(provider=s.embedding_model)
        if s.embedding_base_url:
            path = "/health" if s.embedding_protocol == "autodl_bge" else "/models"
            emb = await self._probe(
                "GET", f"{s.embedding_base_url.rstrip('/')}{path}",
                {"Authorization": f"Bearer {s.embedding_api_key}"} if s.embedding_api_key else {},
            )
            emb.provider = s.embedding_model

        rr = HealthItem(provider=s.rerank_protocol)
        if s.rerank_health_url:
            rr = await self._probe("GET", s.rerank_health_url)
            rr.provider = s.rerank_protocol
        elif not s.rerank_url:
            rr.detail = "未配置"

        return {"llm": asdict(llm), "embedding": asdict(emb), "reranker": asdict(rr)}
