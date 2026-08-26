"""鉴权 RAG 主管线（SDD §4.1）：召回→权限过滤→重排→流式生成。

以异步生成器产出 (event, data) 事件；SSE 层仅做格式化。
事件序（规范）：message_start → delta* → sources → unauthorized? → done | error
"""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Callable

from app.gateway.milvus_store import MilvusStore
from app.gateway.model_gateway import ModelGateway, ModelUnavailable
from app.retrieval.faq_cache import FaqCacheService
from app.retrieval.hybrid import Hit, fuse

PROMPT_BUDGET_CHARS = 6000   # vLLM max-model-len=8192 的粗粒度字符预算（SDD §7）


@dataclass
class ChainContext:
    gateway: ModelGateway
    store_provider: Callable[[], MilvusStore]
    faq_cache: FaqCacheService
    backend_base_url: str
    internal_token: str
    dense_top_k: int = 50
    keyword_top_k: int = 20
    keyword_timeout_ms: int = 200
    rrf_k: int = 60
    rerank_top_n: int = 6
    _client_holder: list = field(default_factory=list)
    _prebuilt_client: httpx.AsyncClient | None = None

    def backend_client(self):
        if self._prebuilt_client is not None:
            return self._prebuilt_client
        if not self._client_holder:
            self._client_holder.append(__import__("httpx").AsyncClient())
        return self._client_holder[0]


def build_prompt(question: str, contexts: list[dict]) -> str:
    """contexts: [{citation,title,content}]；超预算时从尾部裁剪。"""
    lines = []
    used = 0
    for c in contexts:
        block = f"[{c['citation']}]（《{c['title']}》）{c['content']}"
        if used + len(block) > PROMPT_BUDGET_CHARS and lines:
            break
        lines.append(block)
        used += len(block)
    ctx_text = "\n\n".join(lines)
    return (
        "你是企业知识库助手。请严格依据以下知识片段回答用户问题，"
        "引用处使用 [n] 标注对应片段编号；片段不足以回答时明确说明缺少的信息，禁止编造。\n\n"
        f"知识片段：\n{ctx_text}\n\n用户问题：{question}"
    )


async def run_stream(ctx: ChainContext, *, user_id: int, department_id: int | None,
                     is_super: bool, session_id: int | None,
                     question: str) -> AsyncIterator[tuple[str, dict]]:
    started = time.perf_counter()
    yield "message_start", {"session_id": session_id, "question": question}

    answer_parts: list[str] = []
    recalled: list[int] = []
    authorized: list[int] = []
    unauthorized: list[int] = []
    sources: list[dict] = []
    degraded = False
    faq_hit = False
    provider = "primary" if not getattr(ctx.gateway, "_using_fallback", False) else "fallback"
    prompt_tokens = completion_tokens = 0

    try:
        # ---- FAQ 两级缓存 ----
        try:
            hit = await ctx.faq_cache.lookup(question)
        except Exception:
            hit = None
        if hit is not None:
            faq_hit = True
            answer_parts.append(hit.answer)
            yield "delta", {"delta_text": hit.answer}
            yield "sources", {"items": [{"citation": 0, "faq_id": hit.faq_id,
                                         "title": "FAQ 标准答案", "via": hit.via}]}
            elapsed = int((time.perf_counter() - started) * 1000)
            yield "done", {"faq_hit": True, "degraded": False, "provider": "cache",
                           "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                           "response_time_ms": elapsed}
            await _send_log(ctx, session_id=session_id, user_id=user_id,
                            question=question, answer=hit.answer,
                            recalled=[], authorized=[], unauthorized=[],
                            faq_hit=True, degraded=False, ms=elapsed)
            return

        # ---- 双路并发召回（kw 腿 200ms 熔断，NFR-09）----
        async def _dense():
            vector = await ctx.gateway.embed([question])
            store = ctx.store_provider()
            hits = store.search_dense(vector[0], top_k=ctx.dense_top_k)
            return [Hit(unit_id=h.unit_id, seq=h.seq, content=h.content) for h in hits]

        async def _keyword():
            resp = await ctx.backend_client().get(
                f"{ctx.backend_base_url}/internal/search/keyword",
                params={"q": question, "limit": ctx.keyword_top_k},
                headers={"X-Internal-Token": ctx.internal_token},
            )
            resp.raise_for_status()
            return [Hit(unit_id=c["unit_id"], seq=c["seq"],
                        content=c["content"], title=c.get("unit_title", ""))
                    for c in resp.json().get("chunks", [])]

        # 双路独立执行：kw 腿 200ms 熔断只影响自己，绝不连坐取消 dense（NFR-09）
        dense_task = asyncio.create_task(_dense())
        kw_hits: list[Hit] = []
        try:
            kw_hits = await asyncio.wait_for(_keyword(), timeout=ctx.keyword_timeout_ms / 1000)
        except Exception:
            degraded = True          # 关键词腿超时/失败：仅弃用该路
        try:
            dense_hits = await dense_task
        except Exception:
            # embedding 故障：降级纯关键词（放宽时限重试一次）
            dense_hits = []
            try:
                kw_hits = await asyncio.wait_for(_keyword(), timeout=1.5)
            except Exception as e:
                raise ModelUnavailable(f"dense 与 keyword 双路均不可用: {e}") from e
            degraded = True

        fused = fuse(dense_hits, kw_hits, k=ctx.rrf_k)
        recalled = list(dict.fromkeys(h.unit_id for h in fused))

        # ---- 权限回调过滤（ADR-005）----
        unit_meta: dict[str, dict] = {}
        if recalled:
            resp = await ctx.backend_client().post(
                f"{ctx.backend_base_url}/api/knowledge/check-permissions",
                headers={"X-Internal-Token": ctx.internal_token},
                json={"user_id": user_id, "unit_ids": recalled},
            )
            resp.raise_for_status()
            payload = resp.json()["data"]
            authorized = payload["authorized"]
            unauthorized = payload["unauthorized"]
            unit_meta = payload.get("units", {})
        else:
            authorized, unauthorized = [], []

        allowed_set = set(authorized)
        candidates = [h for h in fused if h.unit_id in allowed_set]

        if not candidates:
            hint = "知识库中暂未找到与该问题相关的资料，建议补充相关文档或换个问法。"
            answer_parts.append(hint)
            yield "delta", {"delta_text": hint}
            yield "unauthorized", {"units": [
                {"unit_id": i, "title": unit_meta.get(str(i), {}).get("title", f"单元{i}")}
                for i in unauthorized]}
            elapsed = int((time.perf_counter() - started) * 1000)
            yield "done", {"faq_hit": False, "degraded": degraded, "provider": "none",
                           "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                           "response_time_ms": elapsed}
            await _send_log(ctx, session_id=session_id, user_id=user_id,
                            question=question, answer=hint,
                            recalled=recalled, authorized=authorized,
                            unauthorized=unauthorized, faq_hit=False,
                            degraded=degraded, ms=elapsed)
            return

        # ---- 重排（失败回退 RRF 序）----
        try:
            scores = await ctx.gateway.rerank(question, [h.content for h in candidates])
            ranked = [c for _, c in sorted(zip(scores, candidates),
                                           key=lambda pair: pair[0], reverse=True)]
        except Exception:
            ranked = list(candidates)
        top = ranked[: ctx.rerank_top_n]

        contexts = [{"citation": i + 1, "title": (h.title or
                                                  unit_meta.get(str(h.unit_id), {}).get("title", "")),
                     "content": h.content}
                    for i, h in enumerate(top)]
        prompt = build_prompt(question, contexts)
        prompt_tokens = max(1, len(prompt) // 2)

        # ---- 流式生成（内联发射 delta）----
        messages = [
            {"role": "system", "content": "你是严谨的企业知识库助手。"},
            {"role": "user", "content": prompt},
        ]
        async for delta in ctx.gateway.chat_stream(messages):
            answer_parts.append(delta)
            yield "delta", {"delta_text": delta}
        full = "".join(answer_parts)

        yield "sources", {"items": [
            {"citation": c["citation"], "unit_id": top[i].unit_id,
             "seq": top[i].seq, "title": c["title"]}
            for i, c in enumerate(contexts)
        ]}
        if unauthorized:
            yield "unauthorized", {"units": [
                {"unit_id": i, "title": unit_meta.get(str(i), {}).get("title", f"单元{i}")}
                for i in unauthorized]}

        elapsed = int((time.perf_counter() - started) * 1000)
        completion_tokens = max(1, len(full) // 2)
        yield "done", {"faq_hit": False, "degraded": degraded, "provider": provider,
                       "prompt_tokens": prompt_tokens,
                       "completion_tokens": completion_tokens,
                       "total_tokens": prompt_tokens + completion_tokens,
                       "response_time_ms": elapsed}
        await _send_log(ctx, session_id=session_id, user_id=user_id,
                        question=question, answer="".join(answer_parts),
                        recalled=recalled, authorized=authorized,
                        unauthorized=unauthorized, faq_hit=False,
                        degraded=degraded, ms=elapsed,
                        p_tok=prompt_tokens, c_tok=completion_tokens)

    except ModelUnavailable as e:
        yield "error", {"message": str(e) or "模型服务不可用"}
    except ApiChainError as e:
        yield "error", {"message": e.message}


class ApiChainError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


async def _send_log(ctx: ChainContext, **kw) -> None:
    body = {
        "session_id": kw.get("session_id"),
        "user_id": kw["user_id"],
        "question": kw["question"],
        "answer": kw.get("answer", ""),
        "recalled_unit_ids": kw.get("recalled", []),
        "authorized_unit_ids": kw.get("authorized", []),
        "unauthorized_unit_ids": kw.get("unauthorized", []),
        "faq_hit": kw.get("faq_hit", False),
        "degraded": kw.get("degraded", False),
        "prompt_tokens": kw.get("p_tok", 0),
        "completion_tokens": kw.get("c_tok", 0),
        "total_tokens": kw.get("p_tok", 0) + kw.get("c_tok", 0),
        "response_time_ms": kw.get("ms", 0),
    }
    try:
        await ctx.backend_client().post(
            f"{ctx.backend_base_url}/internal/qa-logs",
            headers={"X-Internal-Token": ctx.internal_token},
            json=body,
        )
    except Exception:
        pass  # 日志尽力而为


__all__ = ["ChainContext", "run_stream", "build_prompt", "ApiChainError"]
