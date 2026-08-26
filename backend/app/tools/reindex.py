"""向量索引全量重建（ADR-003）：以 MySQL 正本为准，逐单元替换 Milvus 索引。

用法（backend 容器内）：
    python -m app.tools.reindex            # 增量补齐（跳过已索引单元）
    python -m app.tools.reindex --force    # 忽略失败缓存，全部重刷
"""
from __future__ import annotations

import sys

from sqlalchemy.orm import Session

from app.models import KnowledgeChunk, KnowledgeUnit
from app.services.import_pipeline import ImportPipeline


def reindex_all(db: Session, *, force: bool = False) -> None:
    pipeline = ImportPipeline(lambda: SessionLocal(db))
    units = db.query(KnowledgeUnit).filter(KnowledgeUnit.status == 1).all()
    ok_count = failed = skipped = 0
    for unit in units:
        chunks = (db.query(KnowledgeChunk)
                  .filter(KnowledgeChunk.unit_id == unit.id)
                  .order_by(KnowledgeChunk.seq_no).all())
        items = [(c.seq_no, c.content) for c in chunks]
        if not items:
            continue
        try:
            pipeline.index_chunks(unit.id, items)
            ok_count += 1
            print(f"[ok] {unit.unit_code} {unit.title} ({len(items)} 片)")
        except Exception as e:
            failed += 1
            print(f"[fail] {unit.unit_code} {unit.title}: {str(e)[:120]}")
    _ = force, skipped
    print(f"[done] 成功 {ok_count} / 失败 {failed}")


def SessionLocal(db: Session | None = None):  # pragma: no cover - 供管线工厂复用
    from app.db import SessionLocal as _SL
    return _SL()


if __name__ == "__main__":
    from app.db import SessionLocal as _make
    session = _make()
    try:
        reindex_all(session, force="--force" in sys.argv)
    finally:
        session.close()
