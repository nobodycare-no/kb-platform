"""DeclarativeBase 与公共 Mixin。"""
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    """全局唯一 declarative base；models 包内所有表注册到 Base.metadata。"""


class TimestampMixin:
    """created_at / updated_at 由数据库维护。"""

    @declared_attr
    def created_at(cls) -> Mapped[datetime]:
        return mapped_column(DateTime, server_default=func.now())

    @declared_attr
    def updated_at(cls) -> Mapped[datetime]:
        return mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
