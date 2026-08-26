"""四维数据权限服务——evaluate() 纯函数之上的 DB 取数包装（SDD §6）。

缓存策略（FR-C04 / NFR-02）：
- permission_codes：RBAC 每请求都会查 → Redis 快照，watermark 取授权三表
  MAX(created_at) 之和（任一变更自动换 key 失效），TTL 300s；
- perms_by_unit：RAG 热路径批量取数 → 全量快照按 watermark 缓存；
- Redis 不可用时全部优雅回落数据库直查。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import RolePermission, UnitPermission, UserRole
from app.services.permission_engine import CheckResult, UserCtx, evaluate

_TTL = 300


def _to_ts(m) -> float:
    """MAX(created_at) 结果兼容：datetime(MySQL/ORM) / str(SQLite裸查) / 数值。"""
    if m is None:
        return 0.0
    if isinstance(m, (int, float)):
        return float(m)
    if hasattr(m, "timestamp"):
        return float(m.timestamp())
    from datetime import datetime
    return datetime.fromisoformat(str(m)).timestamp()


class PermissionService:
    def __init__(self, db: Session, redis_client: Any | None = None):
        self.db = db
        self.redis = redis_client

    # ---------- watermark ----------

    def _wm(self) -> int:
        """授权相关数据水印：任一变更即产生新 key，旧缓存自然失效。"""
        total = 0.0
        for sql in ("SELECT MAX(created_at) AS m FROM user_roles",
                    "SELECT MAX(created_at) AS m FROM role_permissions",
                    "SELECT MAX(updated_at) AS m FROM roles"):
            total += _to_ts(self.db.execute(text(sql)).mappings().one()["m"])
        return int(total)

    def _units_wm(self) -> int:
        return int(_to_ts(self.db.execute(text(
            "SELECT MAX(created_at) AS m FROM unit_permissions"
        )).mappings().one()["m"]))

    # ---------- 缓存原语 ----------

    def _cache_get(self, key: str):
        if self.redis is None:
            return None
        try:
            raw = self.redis.get(key)
            return json.loads(raw) if raw else None
        except Exception:
            return None

    def _cache_set(self, key: str, value) -> None:
        if self.redis is None:
            return
        try:
            self.redis.set(key, json.dumps(value), ex=_TTL)
        except Exception:
            pass

    # ---------- 对外能力 ----------

    def user_ctx(self, *, user_id: int, department_id: int | None,
                 is_super: bool = False) -> UserCtx:
        role_ids = {r[0] for r in
                    self.db.query(UserRole.role_id).filter(UserRole.user_id == user_id)}
        dept_ids: set[int] = {department_id} if department_id is not None else set()
        return UserCtx(user_id=user_id, dept_ids=frozenset(dept_ids),
                       role_ids=frozenset(role_ids), is_super=is_super)

    def permission_codes(self, user_id: int) -> list[str]:
        """用户 → 角色 → 操作权限码（去重）。带 Redis 快照。"""
        key = f"perm:codes:{user_id}:{self._wm()}"
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        rows = (
            self.db.query(RolePermission.permission_code)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .filter(UserRole.user_id == user_id)
            .distinct()
            .all()
        )
        codes = [r[0] for r in rows]
        self._cache_set(key, codes)
        return codes

    def perms_by_unit(self, unit_ids: list[int]) -> dict[int, list[tuple[str, int | None]]]:
        """批量取知识单元的权限实体配置。全表快照缓存（RAG 热路径）。"""
        result: dict[int, list[tuple[str, int | None]]] = {uid: [] for uid in unit_ids}
        if not unit_ids:
            return result

        wm = self._units_wm()
        key = f"perm:units:{wm}"
        snapshot = self._cache_get(key)
        if snapshot is None:
            rows = self.db.query(
                UnitPermission.unit_id, UnitPermission.target_type, UnitPermission.target_id
            ).all()
            snapshot = {}
            for uid, t, tid in rows:
                snapshot.setdefault(str(uid), []).append([t, tid])
            self._cache_set(key, snapshot)

        for uid in unit_ids:
            for t, tid in snapshot.get(str(uid), []):
                result.setdefault(uid, []).append((t, tid))
        return result

    def check(self, *, user_id: int, department_id: int | None, is_super: bool,
              unit_ids: list[int]) -> CheckResult:
        ctx = self.user_ctx(user_id=user_id, department_id=department_id, is_super=is_super)
        return evaluate(self.perms_by_unit(unit_ids), ctx)
