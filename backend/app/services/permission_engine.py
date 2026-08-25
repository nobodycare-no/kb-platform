"""四维数据权限引擎——纯判定层（SRD FR-C / SDD §6）。

设计约束：
- 本模块零 IO：DB 取数与 Redis 快照缓存由上层 PermissionService（Task 2.2 后半）
  包装；纯函数保证可对判定矩阵做数据驱动测试。
- 判定语义：global / department / role / user 任一实体命中即放行（OR）；
  无任何配置默认拒绝（默认安全）；超管旁路。
"""
from typing import Iterable, NamedTuple

# (target_type, target_id)；target_type ∈ {global, department, role, user}
# global 的 target_id 恒为 None
Perm = tuple[str, int | None]


class UserCtx(NamedTuple):
    user_id: int
    dept_ids: frozenset[int]
    role_ids: frozenset[int]
    is_super: bool = False


class CheckResult(NamedTuple):
    authorized: list[int]
    unauthorized: list[int]


def _perm_hit(perm: Perm, ctx: UserCtx) -> bool:
    target_type, target_id = perm
    if target_type == "global":
        return True
    if target_type == "department":
        return target_id in ctx.dept_ids
    if target_type == "role":
        return target_id in ctx.role_ids
    if target_type == "user":
        return target_id == ctx.user_id
    return False  # 未知类型一律不生效（默认安全）


def evaluate(perms_by_unit: dict[int, list[Perm]], ctx: UserCtx) -> CheckResult:
    """按入参顺序逐单元判定；输出保持输入顺序且互斥分区。"""
    authorized: list[int] = []
    unauthorized: list[int] = []
    for unit_id, perms in perms_by_unit.items():
        if ctx.is_super or any(_perm_hit(p, ctx) for p in perms):
            authorized.append(unit_id)
        else:
            unauthorized.append(unit_id)
    return CheckResult(authorized=authorized, unauthorized=unauthorized)


def merge_units(*id_lists: Iterable[int]) -> list[int]:
    """多路召回 unit_id 按出现顺序去重合并（RRF 前的候选集准备）。"""
    seen: dict[int, None] = {}
    for ids in id_lists:
        for unit_id in ids:
            seen.setdefault(unit_id, None)
    return list(seen)


__all__ = ["UserCtx", "CheckResult", "evaluate", "merge_units"]
