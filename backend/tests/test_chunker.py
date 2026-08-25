"""chunker 单元测试（TDD，SRD FR-B02 / SDD §7 切片参数）。"""
import pytest

from app.services.chunker import Chunk, chunk_text


def test_empty_content_returns_empty_list():
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_short_text_single_chunk():
    chunks = chunk_text("短文本内容", size=500, overlap=50)
    assert len(chunks) == 1
    assert chunks[0].seq_no == 0
    assert chunks[0].text == "短文本内容"


def test_long_chinese_no_punctuation_windows():
    text = "内" * 1200
    chunks = chunk_text(text, size=500, overlap=50)
    assert all(isinstance(c, Chunk) for c in chunks)
    assert all(0 < len(c.text) <= 500 for c in chunks)
    # 覆盖完整性：首片从 0 开始，末片覆盖结尾
    assert chunks[0].text == text[:500]
    assert text.endswith(chunks[-1].text[-20:])
    # 每片均为原文子串且窗口起点单调推进（步长 = size - overlap）
    starts = [text.find(c.text) for c in chunks]
    assert all(s >= 0 for s in starts)
    assert starts == sorted(starts)


def test_exact_boundary_single_chunk():
    text = "字" * 500
    chunks = chunk_text(text, size=500, overlap=50)
    assert len(chunks) == 1 and chunks[0].text == text


@pytest.mark.parametrize("size,overlap", [(0, 0), (100, -1), (10, 50), (-5, 0)])
def test_invalid_size_overlap_rejected(size, overlap):
    with pytest.raises(ValueError):
        chunk_text("abc", size=size, overlap=overlap)


def test_markdown_heading_aware_splitting():
    section_a = "# 制度标题\n" + "甲" * 300
    section_b = "## 附则\n" + "乙" * 700
    content = f"{section_a}\n{section_b}"
    chunks = chunk_text(content, is_markdown=True, size=500, overlap=50)

    joined = "\n".join(c.text for c in chunks)
    assert "# 制度标题" in joined and "## 附则" in joined
    # 标题切节生效：不存在跨甲/乙两节的粘连片段
    for c in chunks:
        assert not ("乙" in c.text and "甲" in c.text)


def test_markdown_multiple_headings_order_preserved():
    content = "\n".join([
        "# 一、总则",
        "总则内容" * 50,
        "## 二、考勤",
        "考勤内容" * 60,
        "### 三、假期",
        "假期内容" * 40,
    ])
    chunks = chunk_text(content, is_markdown=True, size=400, overlap=40)
    flat = "\n---\n".join(c.text for c in chunks)
    for kw in ("一、总则", "二、考勤", "三、假期"):
        assert kw in flat
    assert [c.seq_no for c in chunks] == list(range(len(chunks)))


def test_seq_no_contiguous_and_nonempty():
    text = ("段落。" * 200) + "\n\n" + ("尾段！" * 100)
    chunks = chunk_text(text, size=300, overlap=30)
    assert [c.seq_no for c in chunks] == list(range(len(chunks)))
    assert all(c.text.strip() for c in chunks)
