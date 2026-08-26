"""知识沉淀接口（SRD FR-F / AC-07/08）：挖掘、审核发布、缺口。"""
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import get_current_user, require_perms
from app.core.errors import ApiError
from app.core.redis_client import get_redis
from app.core.responses import ok
from app.db import get_db
from app.models import Faq, KnowledgeGap, User
from app.services.settlement_service import approve_and_cache, run_mining

router = APIRouter(prefix="/api/settlement", tags=["settlement"])


@router.get("/faqs/recommendations")
def recommendations(db: Annotated[Session, Depends(get_db)],
                    _: Annotated[User, Depends(get_current_user)]):
    rows = (db.query(Faq).filter(Faq.status == "pending_review")
            .order_by(Faq.id.desc()).limit(100).all())
    return ok([{"id": f.id, "question": f.question, "answer": f.answer,
                "source_type": f.source_type} for f in rows])


@router.get("/faqs/published")
def published(db: Annotated[Session, Depends(get_db)],
              _: Annotated[User, Depends(get_current_user)]):
    rows = (db.query(Faq).filter(Faq.status == "published")
            .order_by(Faq.hit_count.desc(), Faq.id.desc()).limit(200).all())
    return ok([{"id": f.id, "question": f.question, "answer": f.answer,
                "hit_count": f.hit_count} for f in rows])


class ReviewRequest(BaseModel):
    action: str                     # approve | reject
    edited_answer: str | None = None


@router.post("/faqs/{faq_id}/review")
async def review(
    faq_id: int,
    payload: ReviewRequest,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_perms("settle:review"))],
):
    faq = db.query(Faq).filter(Faq.id == faq_id).first()
    if faq is None:
        raise ApiError(404, 4404, "FAQ 不存在")

    if payload.action == "approve":
        from app.core.deps import resolve_user  # noqa: F401
        approve_and_cache(db, faq_id, payload.edited_answer,
                          redis_client=get_redis(),
                          internal_token=get_settings().internal_token,
                          ai_base_url=get_settings().ai_service_base_url)
        return ok({"status": "published"})
    if payload.action == "reject":
        faq.status = "rejected"
        db.commit()
        return ok({"status": "rejected"})
    raise ApiError(400, 4400, "action 仅支持 approve/reject")


@router.get("/knowledge-gaps")
def gaps(db: Annotated[Session, Depends(get_db)],
         _: Annotated[User, Depends(get_current_user)]):
    rows = (db.query(KnowledgeGap).filter(KnowledgeGap.status != "ignored")
            .order_by(KnowledgeGap.ask_count.desc()).limit(100).all())
    return ok([{"id": g.id, "question_pattern": g.question_pattern,
                "ask_count": g.ask_count, "status": g.status,
                "last_asked_at": g.last_asked_at.isoformat() if g.last_asked_at else None}
               for g in rows])


class MineTrigger(BaseModel):
    days: int = 7
    min_freq: int = 3


@router.post("/mine")
def trigger_mine(payload: MineTrigger | None = None,
                 request: Request = None,
                 db: Annotated[Session, Depends(get_db)] = None,
                 _: Annotated[User, Depends(require_perms("settle:review"))] = None):
    body = payload or MineTrigger()
    result = run_mining(db, days=body.days, min_freq=body.min_freq)
    return ok(result)
