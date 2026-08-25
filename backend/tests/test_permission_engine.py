"""四维数据权限判定矩阵（SRD FR-C、SDD §6）。数据驱动，覆盖 OR 语义与默认拒绝。"""
import pytest

from app.services.permission_engine import UserCtx, evaluate

CTX = UserCtx(user_id=7, dept_ids=frozenset({3}), role_ids=frozenset({11}))

MATRIX = [
    # ---- 单实体 ----
    ([("global", None)], True, "全局公开即放行"),
    ([("department", 3)], True, "部门命中"),
    ([("department", 99)], False, "部门不命中"),
    ([("role", 11)], True, "角色命中"),
    ([("role", 12)], False, "角色不命中"),
    ([("user", 7)], True, "个人命中"),
    ([("user", 8)], False, "个人不命中"),
    ([], False, "无任何配置=默认拒绝(FR-C01)"),
    # ---- 多实体叠加（OR 语义）----
    ([("department", 99), ("role", 11)], True, "前不中后中"),
    ([("user", 8), ("global", None)], True, "任一命中即放行"),
    ([("department", 99), ("role", 12), ("user", 8)], False, "全不中则拒绝"),
    # ---- 异常形态 ----
    ([("unknown_type", 1)], False, "未知类型忽略→拒绝"),
    ([("global", None), ("unknown_type", 1)], True, "未知类型不影响有效命中"),
]


@pytest.mark.parametrize("perms,allowed,desc", MATRIX, ids=[c[2] for c in MATRIX])
def test_matrix_single_unit(perms, allowed, desc):
    res = evaluate({101: perms}, CTX)
    assert (101 in res.authorized) is allowed, desc
    assert (101 in res.unauthorized) is not allowed


def test_superuser_bypasses_even_empty_perms():
    sup = UserCtx(user_id=1, dept_ids=frozenset(), role_ids=frozenset(), is_super=True)
    res = evaluate({201: [], 202: [("department", 999)]}, sup)
    assert res.authorized == [201, 202]
    assert res.unauthorized == []


def test_output_order_preserved_and_partitioned():
    perms_by_unit = {
        3: [("global", None)],
        1: [],
        2: [("user", 7)],
        4: [("role", 12)],
    }
    res = evaluate(perms_by_unit, CTX)
    assert res.authorized == [3, 2]
    assert res.unauthorized == [1, 4]


def test_merge_units_dedup_keeps_order():
    from app.services.permission_engine import merge_units

    assert list(merge_units([5, 6, 5], [6, 7])) == [5, 6, 7]
