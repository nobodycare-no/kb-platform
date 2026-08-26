"""知识沉淀服务（SRD FR-F）：高频问题挖掘 → 待审 FAQ；缺口识别。

v1 简化：以归一化问题的精确频次做聚类（阈值 MINE_MIN_FREQ）；
embedding 语义聚类作为 S8 增强。发布时写两级缓存（Redis L1 + Milvus L2）。
"""
from __future__ import annotations

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Faq, KnowledgeGap, QaAccessLog


def _normalize(q: str) -> str:
    """与 ai-service normalize() 保持一致：NFKC 全半角统一 + 去空白 + 小写。"""
    import unicodedata
    t = unicodedata.normalize("NFKC", q or "")
    return "".join(t.split()).lower()


def run_mining(db: Session, *, days: int = 7, min_freq: int = 3,
               gap_threshold_days: int = 7) -> dict:
    """扫描近 N 天问答日志，产出候选 FAQ 与知识缺口。可手动触发。"""
    rows = db.execute(
        text("SELECT user_id, question, answer, recalled_unit_ids, unauthorized_unit_ids "
             "FROM qa_access_logs WHERE created_at > DATE_SUB(NOW(), INTERVAL :days DAY)"),
        {"days": days},
    ).mappings().all()

    # ---- 频次聚合 ----
    freq: dict[str, dict] = {}
    for r in rows:
        key = _normalize(r["question"])
        if not key:
            continue
        entry = freq.setdefault(key, {
            "sample": r["question"], "count": 0,
            "last_answer": "", "nothing_found": False})
        entry["count"] += 1
        entry["last_answer"] = r["answer"] or ""
        recalled = r["recalled_unit_ids"] or []
        unauthorized = r["unauthorized_unit_ids"] or []
        entry["nothing_found"] = (not recalled) or (
            len(set(recalled) & (set(recalled) - set(unauthorized))) == 0)

    created_faqs = 0
    published_questions = {
        _normalize(f.question) for f in db.query(Faq).filter(Faq.status == "published")
    }
    for key, info in freq.items():
        if key in published_questions or info["count"] < min_freq:
            continue
        exists = db.query(Faq).filter(Faq.status == "pending_review",
                                      Faq.question == info["sample"]).first()
        if exists:
            continue
        if not info["nothing_found"]:
            db.add(Faq(question=info["sample"], answer=info["last_answer"],
                       source_type="auto_mined", status="pending_review"))
            created_faqs += 1

    # ---- 知识缺口：无召回或全部无权 ----
    created_gaps = 0
    updated_gaps = 0
    for key, info in freq.items():
        if not info["nothing_found"]:
            continue
        gap = db.query(KnowledgeGap).filter(KnowledgeGap.question_pattern == info["sample"]).first()
        if gap:
            gap.ask_count += info["count"]
            gap.last_asked_at = gap.updated_at
            updated_gaps += 1
        else:
            db.add(KnowledgeGap(question_pattern=info["sample"],
                                sample_questions=[info["sample"]],
                                ask_count=info["count"], status="unresolved"))
            created_gaps += 1

    db.commit()
    return {"scanned": len(rows), "created_faqs": created_faqs,
            "created_gaps": created_gaps, "updated_gaps": updated_gaps}


def approve_and_cache(db: Session, faq_id: int, edited_answer: str | None,
                      *, redis_client=None,
                      ai_base_url: str | None = None,
                      internal_token: str | None = None) -> None:
    """审核通过：置 published + 写 Redis L1 + 通知 ai-service 写入语义向量。"""
    from app.core.config import get_settings

    faq = db.query(Faq).filter(Faq.id == faq_id).first()
    if faq is None:
        raise ValueError("FAQ 不存在")
    if edited_answer:
        faq.answer = edited_answer
    faq.status = "published"
    db.commit()

    s = get_settings()
    token = internal_token if internal_token is not None else s.internal_token
    base = ai_base_url or s.ai_service_base_url

    if redis_client is not None:
        try:
            key = "faq:h:" + __import__("hashlib").md5(
                _normalize(faq.question).encode()).hexdigest()
            redis_client.set(key, __import__("json").dumps(
                {"faq_id": faq.id, "answer": faq.answer}))
        except Exception:
            pass  # 缓存失败不影响发布

    try:
        httpx.post(f"{base}/internal/faq/upsert",
                   headers={"X-Internal-Token": token},
                   json={"faq_id": faq.id, "question": faq.question}, timeout=30)
    except Exception:
        pass  # 语义缓存失败不影响发布，下次挖掘会补
