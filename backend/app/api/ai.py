"""AI 问答接口：会话管理 + 鉴权流式问答代理（backend 不碰模型）。"""
from collections.abc import AsyncIterator
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import get_current_user
from app.core.errors import ApiError
from app.core.responses import ok
from app.db import get_db
from app.models import QaAccessLog, QaSession, User

router = APIRouter(prefix="/api/ai", tags=["ai"])


class SessionCreate(BaseModel):
    title: str | None = None


class ChatRequest(BaseModel):
    question: str
    session_id: int | None = None


def _own_session(db: Session, user: User, session_id: int) -> QaSession:
    s = db.query(QaSession).filter(QaSession.id == session_id).first()
    if s is None or s.user_id != user.id:
        raise ApiError(404, 4404, "会话不存在")
    return s


@router.post("/sessions")
def create_session(
    payload: SessionCreate | None = None,
    db: Annotated[Session, Depends(get_db)] = None,
    user: Annotated[User, Depends(get_current_user)] = None,
):
    _ = payload
    title = (payload.title if payload and payload.title else "新会话")[:128]
    s = QaSession(user_id=user.id, title=title)
    db.add(s)
    db.commit()
    return ok({"session_id": s.id, "title": s.title})


@router.get("/sessions")
def list_sessions(
    db: Annotated[Session, Depends(get_db)] = None,
    user: Annotated[User, Depends(get_current_user)] = None,
):
    rows = (db.query(QaSession).filter(QaSession.user_id == user.id)
            .order_by(QaSession.updated_at.desc()).limit(100).all())
    return ok([{"session_id": s.id, "title": s.title,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None}
               for s in rows])


@router.get("/sessions/{session_id}/messages")
def session_messages(
    session_id: int,
    db: Annotated[Session, Depends(get_db)] = None,
    user: Annotated[User, Depends(get_current_user)] = None,
):
    _own_session(db, user, session_id)
    logs = (db.query(QaAccessLog)
            .filter(QaAccessLog.session_id == session_id, QaAccessLog.user_id == user.id)
            .order_by(QaAccessLog.id).all())
    messages: list[dict] = []
    for log in logs:
        messages.append({"role": "user", "content": log.question,
                         "created_at": log.created_at.isoformat()})
        msg = {"role": "assistant", "content": log.answer or "",
               "faq_hit": bool(log.faq_hit), "degraded": bool(log.degraded),
               "sources": [{"unit_id": i} for i in (log.authorized_unit_ids or [])]}
        if log.unauthorized_unit_ids:
            msg["unauthorized_unit_ids"] = log.unauthorized_unit_ids
        messages.append(msg)
    return ok(messages)


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)] = None,
    user: Annotated[User, Depends(get_current_user)] = None,
):
    if not payload.question.strip():
        raise ApiError(400, 4400, "问题不能为空")

    if payload.session_id is None:
        s = QaSession(user_id=user.id, title=payload.question[:20])
        db.add(s)
        db.commit()
        session_id = s.id
    else:
        _own_session(db, user, payload.session_id)
        session_id = payload.session_id

    settings = get_settings()
    upstream_payload = {
        "user_id": user.id,
        "department_id": user.department_id,
        "is_super": bool(user.is_super),
        "session_id": session_id,
        "question": payload.question,
    }

    async def relay() -> AsyncIterator[bytes]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, read=300)) as cli:
            async with cli.stream(
                "POST",
                f"{settings.ai_service_base_url}/internal/rag/stream",
                json=upstream_payload,
                headers={"X-Internal-Token": settings.internal_token},
            ) as resp:
                if resp.status_code != 200:
                    import json as _json

                    err = f"event: error\ndata: {_json.dumps({'message': f'上游服务异常 {resp.status_code}'})}\n\n"
                    yield err.encode("utf-8")
                    return
                async for chunk in resp.aiter_bytes():
                    yield chunk

    return StreamingResponse(relay(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
