"""混合检索融合：RRF（Reciprocal Rank Fusion，ADR-004）。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Hit:
    unit_id: int
    seq: int
    content: str = ""
    title: str = ""


def fuse(dense: Sequence[Hit], keyword: Sequence[Hit], k: int = 60) -> list[Hit]:
    """RRF 融合：score = Σ 1/(k + rank)；同键累加；按分数降序稳定排序。

    首次出现的 Hit 携带其 content/title（两路内容一致性由上游保证）。
    """
    scores: dict[tuple[int, int], float] = {}
    first_seen: dict[tuple[int, int], Hit] = {}

    for ranked_list in (dense, keyword):
        for rank, hit in enumerate(ranked_list):
            key = (hit.unit_id, hit.seq)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            if key not in first_seen:
                first_seen[key] = hit

    ordered_keys = sorted(scores, key=lambda key: (-scores[key],))
    return [
        Hit(unit_id=key[0], seq=key[1],
            content=first_seen[key].content, title=first_seen[key].title)
        for key in ordered_keys
    ]
