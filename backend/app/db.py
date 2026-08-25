"""数据库引擎与会话工厂。URL 全部来自环境变量（见 deploy/.env.example）。"""
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_settings = get_settings()

# 演示规模单实例：pool_pre_ping 防 MySQL 8 小时断连
engine = create_engine(_settings.mysql_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
