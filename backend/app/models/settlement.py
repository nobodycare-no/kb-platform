"""知识沉淀域模型：faqs / knowledge_gaps。"""
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Faq(TimestampMixin, Base):
    __tablename__ = "faqs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    question: Mapped[str] = mapped_column(String(512), index=True)
    answer: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(64), default="")
    related_unit_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    source_type: Mapped[str] = mapped_column(String(16), default="manual")
    status: Mapped[str] = mapped_column(String(16), default="pending_review", index=True)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    reviewer_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class KnowledgeGap(TimestampMixin, Base):
    __tablename__ = "knowledge_gaps"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    question_pattern: Mapped[str] = mapped_column(String(512))
    sample_questions: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    ask_count: Mapped[int] = mapped_column(Integer, default=1)
    last_asked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="unresolved", index=True)
    resolved_unit_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
