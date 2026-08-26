"""数据看板聚合接口（SRD FR-E / AC-06）。"""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.responses import ok
from app.db import get_db
from app.models import KnowledgeUnit, User

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/metrics")
def metrics(db: Annotated[Session, Depends(get_db)],
            _: Annotated[User, Depends(get_current_user)]):
    row = db.execute(text(
        "SELECT COUNT(*) AS total_visits,"
        " COUNT(DISTINCT user_id) AS unique_users,"
        " IFNULL(SUM(total_tokens),0) AS total_tokens,"
        " IFNULL(AVG(response_time_ms),0) AS avg_response_ms"
        " FROM qa_access_logs")).mappings().one()
    unit_count = db.query(KnowledgeUnit).filter(KnowledgeUnit.status == 1).count()
    return ok({
        "total_visits": int(row["total_visits"]),
        "unique_users": int(row["unique_users"]),
        "unit_count": unit_count,
        "total_tokens": int(row["total_tokens"]),
        "avg_response_ms": float(row["avg_response_ms"]),
    })


@router.get("/rankings/questions")
def question_rankings(db: Annotated[Session, Depends(get_db)],
                      _: Annotated[User, Depends(get_current_user)],
                      limit: int = 10):
    rows = db.execute(text(
        "SELECT question, COUNT(*) AS cnt FROM qa_access_logs "
        "GROUP BY question ORDER BY cnt DESC LIMIT :lim"), {"lim": limit}).mappings()
    return ok([{"question": r["question"], "cnt": int(r["cnt"])} for r in rows])


@router.get("/rankings/units")
def unit_rankings(db: Annotated[Session, Depends(get_db)],
                  _: Annotated[User, Depends(get_current_user)],
                  limit: int = 10):
    """按授权命中的知识单元统计热度（JSON_TABLE 展开数组）。"""
    try:
        rows = db.execute(text(
            "SELECT u.title, jt.unit_id, COUNT(*) AS cnt "
            "FROM qa_access_logs l, "
            " JSON_TABLE(l.authorized_unit_ids, '$[*]' COLUMNS(unit_id BIGINT PATH '$')) jt "
            "JOIN knowledge_units u ON u.id = jt.unit_id "
            "GROUP BY jt.unit_id, u.title ORDER BY cnt DESC LIMIT :lim"),
            {"lim": limit}).mappings()
        return ok([{"title": r["title"], "unit_id": int(r["unit_id"]), "cnt": int(r["cnt"])}
                   for r in rows])
    except Exception:
        # SQLite（测试环境）无 JSON_TABLE：Python 端聚合兜底
        from collections import Counter
        from app.models import QaAccessLog
        counter: dict[int, int] = {}
        titles = {u.id: u.title for u in db.query(KnowledgeUnit).all()}
        for log in db.query(QaAccessLog).all():
            for uid in (log.authorized_unit_ids or []):
                counter[uid] = counter.get(uid, 0) + 1
        top = sorted(counter.items(), key=lambda kv: -kv[1])[:limit]
        return ok([{"title": titles.get(uid, f"单元{uid}"), "unit_id": uid, "cnt": cnt}
                   for uid, cnt in top])


@router.get("/stats/tokens")
def token_stats(days: int = 14,
                db: Annotated[Session, Depends(get_db)] = None,
                _: Annotated[User, Depends(get_current_user)] = None):
    _ = days
    rows = db.execute(text(
        "SELECT DATE(created_at) AS day, SUM(total_tokens) AS total_tokens,"
        " AVG(response_time_ms) AS avg_response_ms "
        "FROM qa_access_logs GROUP BY DATE(created_at) ORDER BY day")).mappings()
    return ok([{"day": str(r["day"]), "total_tokens": int(r["total_tokens"]),
                "avg_response_ms": round(float(r["avg_response_ms"] or 0))}
               for r in rows])
