"""问答会话/审计日志模型：qa_sessions / qa_access_logs。"""
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, BigInteger, DateTime, Integer, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class QaSession(TimestampMixin, Base):
    __tablename__ = "qa_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    title: Mapped[str] = mapped_column(String(128), default="新会话")


class QaAccessLog(Base):
    __tablename__ = "qa_access_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recalled_unit_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    authorized_unit_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    unauthorized_unit_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    faq_hit: Mapped[int] = mapped_column(SmallInteger, default=0)
    degraded: Mapped[int] = mapped_column(SmallInteger, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    response_time_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
