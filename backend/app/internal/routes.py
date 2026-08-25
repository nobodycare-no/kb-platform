"""backend 内部端点：关键词召回、问答日志回写（仅 ai-service 可调）。"""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.internal.deps import verify_internal_token
from app.models import KnowledgeChunk, KnowledgeUnit, QaAccessLog

router = APIRouter(prefix="/internal", tags=["internal"])


@router.get("/search/keyword", dependencies=[Depends(verify_internal_token)])
def search_keyword(
    q: Annotated[str, Query(min_length=1, max_length=256)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=20, ge=1, le=50),
):
    """MySQL ngram FULLTEXT 关键词召回腿（混合检索之一，ADR-004）。"""
    try:
        rows = (
            db.query(
                KnowledgeChunk.unit_id,
                KnowledgeChunk.seq_no,
                KnowledgeChunk.content,
                KnowledgeUnit.title,
            )
            .join(KnowledgeUnit, KnowledgeUnit.id == KnowledgeChunk.unit_id)
            .filter(
                KnowledgeUnit.status == 1,
                KnowledgeChunk.content.match(q),   # MATCH ... AGAINST（自然语言模式）
            )
            .limit(limit)
            .all()
        )
    except Exception as e:  # FULLTEXT 异常视为该腿不可用（降级由调用方标记）
        return {"chunks": [], "degraded": True, "detail": str(e)[:200]}

    return {"chunks": [
        {"unit_id": r.unit_id, "seq": r.seq_no, "content": r.content, "unit_title": r.title}
        for r in rows
    ], "degraded": False}


class QaLogRequest(BaseModel):
    session_id: int | None = None
    user_id: int
    question: str
    answer: str = ""
    recalled_unit_ids: list[int] = []
    authorized_unit_ids: list[int] = []
    unauthorized_unit_ids: list[int] = []
    faq_hit: bool = False
    degraded: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    response_time_ms: int = 0


@router.get("/faq/{faq_id}", dependencies=[Depends(verify_internal_token)])
def get_published_faq(faq_id: int, db: Annotated[Session, Depends(get_db)]):
    """FAQ L2 语义命中的答案回源。"""
    row = db.query(Faq).filter(Faq.id == faq_id, Faq.status == "published").first()
    if row is None:
        return {"answer": None}
    return {"question": row.question, "answer": row.answer}


@router.post("/qa-logs", dependencies=[Depends(verify_internal_token)])
def write_qa_log(payload: QaLogRequest, db: Annotated[Session, Depends(get_db)]):
    row = QaAccessLog(
        session_id=payload.session_id,
        user_id=payload.user_id,
        question=payload.question,
        answer=payload.answer,
        recalled_unit_ids=payload.recalled_unit_ids,
        authorized_unit_ids=payload.authorized_unit_ids,
        unauthorized_unit_ids=payload.unauthorized_unit_ids,
        faq_hit=int(payload.faq_hit),
        degraded=int(payload.degraded),
        prompt_tokens=payload.prompt_tokens,
        completion_tokens=payload.completion_tokens,
        total_tokens=payload.total_tokens,
        response_time_ms=payload.response_time_ms,
    )
    db.add(row)
    db.commit()
    return {"log_id": row.id}
