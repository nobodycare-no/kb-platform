"""文档切片器（SRD FR-B02）：Markdown 标题感知 + 滑动窗口。

纯函数、零 IO。参数约束：0 < overlap < size。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")


@dataclass(frozen=True)
class Chunk:
    seq_no: int
    text: str


def chunk_text(content: str, *, is_markdown: bool = False,
               size: int = 500, overlap: int = 50) -> list[Chunk]:
    """切片入口。

    - Markdown：先按标题行切节（标题行归属其后的节），节内滑窗；
    - 普通文本：整体滑窗；
    - 保证：片段非空、长度 ≤ size、seq_no 连续、内容均为原文子串。
    """
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError(f"非法参数: size={size}, overlap={overlap}")

    text = (content or "").strip()
    if not text:
        return []

    sections = _split_markdown(text) if is_markdown else [text]
    pieces: list[str] = []
    for section in sections:
        pieces.extend(_window(section, size, overlap))
    return [Chunk(seq_no=i, text=p) for i, p in enumerate(pieces)]


def _split_markdown(text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if _HEADING_RE.match(line) and current:
            parts.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    parts.append("\n".join(current))
    return [p.strip() for p in parts if p.strip()]


def _window(text: str, size: int, overlap: int) -> list[str]:
    if len(text) <= size:
        return [text]
    step = size - overlap
    out: list[str] = []
    start = 0
    while start < len(text):
        piece = text[start:start + size].strip()
        if piece:
            out.append(piece)
        if start + size >= len(text):
            break
        start += step
    return out or [text[:size]]
