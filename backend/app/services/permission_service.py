"""四维数据权限服务——evaluate() 纯函数之上的 DB 取数包装（SDD §6）。

缓存说明：Redis 快照（FR-C04, P1）在 S5 接入；当前直查，
查询均为批量 IN 且演示数据量小，满足 NFR-02 预算。
"""
from sqlalchemy.orm import Session

from app.models import RolePermission, UnitPermission, UserRole
from app.services.permission_engine import CheckResult, UserCtx, evaluate


class PermissionService:
    def __init__(self, db: Session):
        self.db = db

    def user_ctx(self, *, user_id: int, department_id: int | None, is_super: bool = False) -> UserCtx:
        role_ids = {r[0] for r in self.db.query(UserRole.role_id).filter(UserRole.user_id == user_id)}
        dept_ids: set[int] = {department_id} if department_id is not None else set()
        return UserCtx(
            user_id=user_id,
            dept_ids=frozenset(dept_ids),
            role_ids=frozenset(role_ids),
            is_super=is_super,
        )

    def permission_codes(self, user_id: int) -> list[str]:
        """用户 → 角色 → 操作权限码（去重）。"""
        rows = (
            self.db.query(RolePermission.permission_code)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .filter(UserRole.user_id == user_id)
            .distinct()
            .all()
        )
        return [r[0] for r in rows]

    def perms_by_unit(self, unit_ids: list[int]) -> dict[int, list[tuple[str, int | None]]]:
        """批量取知识单元的权限实体配置。"""
        result: dict[int, list[tuple[str, int | None]]] = {uid: [] for uid in unit_ids}
        if not unit_ids:
            return result
        rows = (
            self.db.query(UnitPermission.unit_id, UnitPermission.target_type, UnitPermission.target_id)
            .filter(UnitPermission.unit_id.in_(unit_ids))
            .all()
        )
        for unit_id, target_type, target_id in rows:
            result.setdefault(unit_id, []).append((target_type, target_id))
        return result

    def check(self, *, user_id: int, department_id: int | None, is_super: bool,
              unit_ids: list[int]) -> CheckResult:
        ctx = self.user_ctx(user_id=user_id, department_id=department_id, is_super=is_super)
        return evaluate(self.perms_by_unit(unit_ids), ctx)
