"""DeclarativeBase、公共 Mixin 与共享主键类型。"""
from datetime import datetime
from typing import Annotated

from sqlalchemy import BigInteger, DateTime, Integer, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    """全局唯一 declarative base；models 包内所有表注册到 Base.metadata。"""


# BigInteger 主键 + SQLite 变体（测试内存库自增），MySQL 下仍为 BIGINT AUTO_INCREMENT
BigIntPK = Annotated[
    int,
    mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
]


class TimestampMixin:
    """created_at / updated_at 由数据库维护。"""

    @declared_attr
    def created_at(cls) -> Mapped[datetime]:
        return mapped_column(DateTime, server_default=func.now())

    @declared_attr
    def updated_at(cls) -> Mapped[datetime]:
        return mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
