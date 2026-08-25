"""RRF 融合纯函数测试（TDD）。"""
from app.retrieval.hybrid import Hit, fuse


def hits(specs):
    return [Hit(unit_id=u, seq=s, content=c, title=t) for u, s, c, t in specs]


def test_fuse_merges_overlap_with_rrf_scores():
    dense = hits([(1, 0, "A", ""), (2, 1, "B", "")])
    kw = hits([(2, 1, "B", ""), (3, 2, "C", "")])
    fused = fuse(dense, kw, k=60)

    keys = [(h.unit_id, h.seq) for h in fused]
    # 重叠文档 (2,1) 两路都命中应排第一；其次 (1,0)；最后 (3,2)
    assert keys[0] == (2, 1)
    assert keys.index((1, 0)) < keys.index((3, 2))


def test_fuse_single_empty_side():
    dense = hits([(5, 3, "X", "")])
    fused = fuse(dense, [], k=60)
    assert [h.unit_id for h in fused] == [5]

    fused2 = fuse([], dense, k=60)
    assert [h.unit_id for h in fused2] == [5]


def test_fuse_stable_for_equal_scores():
    a = hits([(10, 0, "a", "")])
    b = hits([(20, 9, "b", "")])
    fused = fuse(a, b, k=1)  # rank0 与 rank0 同分
    # 稳定排序：dense 先出现者在前
    assert [h.unit_id for h in fused] == [10, 20]


def test_fuse_keeps_first_seen_content():
    dense = hits([(1, 0, "来自向量路", "")])
    kw = hits([(1, 0, "", "标题来自关键词路")])
    fused = fuse(dense, kw)
    assert fused[0].content == "来自向量路"
    assert fused[0].title == ""
