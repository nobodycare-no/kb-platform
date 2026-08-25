"""知识域模型：knowledge_units / knowledge_chunks / unit_permissions / import_tasks。"""
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Integer, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class KnowledgeUnit(TimestampMixin, Base):
    __tablename__ = "knowledge_units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    unit_code: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(String(512), default="")
    category: Mapped[str] = mapped_column(String(64), default="", index=True)
    source_file_name: Mapped[str] = mapped_column(String(255), default="")
    file_type: Mapped[str] = mapped_column(String(16), default="")
    status: Mapped[int] = mapped_column(SmallInteger, default=1, index=True)
    creator_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    unit_id: Mapped[int] = mapped_column(BigInteger, index=True)
    seq_no: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UnitPermission(Base):
    __tablename__ = "unit_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    unit_id: Mapped[int] = mapped_column(BigInteger, index=True)
    target_type: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ImportTask(Base):
    __tablename__ = "import_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_no: Mapped[str] = mapped_column(String(32), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(16), default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    task_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    unit_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
