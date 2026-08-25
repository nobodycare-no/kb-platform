"""FAQ 两级缓存（ADR-007）：L1 Redis 精确 hash → L2 语义向量匹配。

Redis 不可用时优雅降级为仅语义路；全部命中判定纯函数化便于测试。
"""
from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from typing import Any, Protocol

from app.gateway.milvus_store import MilvusStore
from app.gateway.model_gateway import ModelGateway


def normalize(question: str) -> str:
    """归一化：NFKC 全半角统一 + 小写 + 去所有空白。"""
    text = unicodedata.normalize("NFKC", question or "")
    text = "".join(text.split())
    return text.lower()


def faq_hash_key(question: str) -> str:
    return "faq:h:" + hashlib.md5(normalize(question).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FaqHit:
    faq_id: int
    answer: str
    via: str            # "l1" | "l2"
    score: float | None = None   # l2 相似度


class _RedisLike(Protocol):
    def get(self, key: str) -> Any: ...
    def set(self, key: str, value: str, ex: int | None = None) -> Any: ...


class FaqCacheService:
    def __init__(self, *, gateway: ModelGateway, store: MilvusStore,
                 redis_client: _RedisLike | None = None,
                 faq_answer_fetcher=None,
                 exact_sim: float = 0.92):
        """faq_answer_fetcher 异步可调用：faq_id → {"question","answer"}（L2 命中回源）。"""
        self.redis = redis_client
        self.store = store
        self.gateway = gateway
        self.fetch_answer = faq_answer_fetcher or (lambda faq_id: None)
        self.exact_sim = exact_sim

    # ---- L1 ----

    async def lookup_l1(self, question: str) -> FaqHit | None:
        if self.redis is None:
            return None
        try:
            raw = self.redis.get(faq_hash_key(question))
        except Exception:
            return None
        if not raw:
            return None
        data = raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
        try:
            obj = __import__("json").loads(data)
            return FaqHit(faq_id=int(obj["faq_id"]), answer=obj["answer"], via="l1")
        except Exception:
            return None

    async def publish_l1(self, faq_id: int, question: str, answer: str) -> None:
        if self.redis is None:
            return
        try:
            self.redis.set(faq_hash_key(question),
                           __import__("json").dumps({"faq_id": faq_id, "answer": answer}))
        except Exception:
            pass  # 缓存写失败不影响业务

    # ---- L2 ----

    async def lookup_l2(self, question: str) -> FaqHit | None:
        vector = await self.gateway.embed([question])
        if not vector:
            return None
        faq_id, score = self.store.search_faq(vector[0], threshold=self.exact_sim)
        if faq_id is None:
            return None
        info = await self.fetch_answer(faq_id) or {}
        answer = info.get("answer")
        if not answer:
            return None
        return FaqHit(faq_id=faq_id, answer=answer, via="l2", score=score)

    # ---- 组合入口 ----

    async def lookup(self, question: str) -> FaqHit | None:
        hit = await self.lookup_l1(question)
        if hit:
            return hit
        try:
            return await self.lookup_l2(question)
        except Exception:
            return None  # embedding/向量库故障 → 走完整检索链（上层降级）
