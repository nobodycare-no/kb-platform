"""Milvus 派生索引存储层（ADR-003：MySQL 是事实源，本层全部可重建）。

集合：
- kb_chunks   : 知识切片稠密向量（auto_id 主键，业务字段 unit_id/seq/content）
- faq_vectors : 已发布 FAQ 问题向量（faq_id/question）

一致性：写入走 replace（先按业务键删除再插入）；查询 COSINE/HNSW。
"""
from dataclasses import dataclass
from typing import Sequence

from pymilvus import DataType, MilvusClient

KB_COLLECTION = "kb_chunks"
FAQ_COLLECTION = "faq_vectors"


@dataclass
class DenseHit:
    unit_id: int
    seq: int
    content: str
    score: float  # COSINE：越大越相关


class MilvusStore:
    def __init__(self, uri: str, dim: int = 1024, client: MilvusClient | None = None,
                 kb_collection: str = KB_COLLECTION, faq_collection: str = FAQ_COLLECTION):
        self.uri = uri
        self.dim = dim
        self.kb_collection = kb_collection
        self.faq_collection = faq_collection
        self.client = client or MilvusClient(uri=uri)

    # ---------- 集合管理 ----------

    def ensure_collections(self) -> None:
        self._ensure_kb()
        self._ensure_faq()

    def reset(self) -> None:
        """drop 并重建两个集合（reindex / 测试隔离用）。"""
        for name in (self.kb_collection, self.faq_collection):
            if self.client.has_collection(name):
                self.client.drop_collection(name)
        self.ensure_collections()

    def _vector_index_params(self):
        index = MilvusClient.prepare_index_params()
        index.add_index(
            field_name="embedding", index_type="HNSW", metric_type="COSINE",
            params={"M": 16, "efConstruction": 200},
        )
        return index

    def _ensure_kb(self) -> None:
        if self.client.has_collection(self.kb_collection):
            return
        schema = MilvusClient.create_schema(auto_id=True)
        schema.add_field("id", DataType.INT64, is_primary=True)
        schema.add_field("unit_id", DataType.INT64)
        schema.add_field("seq", DataType.INT64)
        schema.add_field("content", DataType.VARCHAR, max_length=4096)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=self.dim)
        self.client.create_collection(
            self.kb_collection, schema=schema, index_params=self._vector_index_params(),
            consistency_level="Strong",
        )

    def _ensure_faq(self) -> None:
        if self.client.has_collection(self.faq_collection):
            return
        schema = MilvusClient.create_schema(auto_id=True)
        schema.add_field("id", DataType.INT64, is_primary=True)
        schema.add_field("faq_id", DataType.INT64)
        schema.add_field("question", DataType.VARCHAR, max_length=1024)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=self.dim)
        self.client.create_collection(
            self.faq_collection, schema=schema, index_params=self._vector_index_params(),
            consistency_level="Strong",
        )

    # ---------- 知识切片 ----------

    def replace_chunks(self, unit_id: int, items: Sequence[tuple[int, str]],
                       vectors: Sequence[list[float]]) -> None:
        """整单元替换（先删后插），供导入/重嵌入使用。"""
        if len(items) != len(vectors):
            raise ValueError(f"chunks/vectors 数量不符: {len(items)} != {len(vectors)}")
        self.delete_unit(unit_id)
        rows = [
            {"unit_id": int(unit_id), "seq": int(seq), "content": text, "embedding": vec}
            for (seq, text), vec in zip(items, vectors)
        ]
        if rows:
            self.client.insert(self.kb_collection, rows)

    def delete_unit(self, unit_id: int) -> None:
        self.client.delete(self.kb_collection, filter=f"unit_id == {int(unit_id)}")

    def search_dense(self, query_vector: list[float], top_k: int = 50) -> list[DenseHit]:
        res = self.client.search(
            self.kb_collection,
            data=[query_vector],
            limit=top_k,
            output_fields=["unit_id", "seq", "content"],
            search_params={"metric_type": "COSINE", "params": {"ef": 128}},
        )
        hits: list[DenseHit] = []
        for row in (res[0] if res else []):
            entity = row.get("entity", {})
            hits.append(DenseHit(
                unit_id=int(entity["unit_id"]),
                seq=int(entity.get("seq", 0)),
                content=str(entity.get("content", "")),
                score=float(row["distance"]),
            ))
        return hits

    def count_chunks_for_unit(self, unit_id: int) -> int:
        rows = self.client.query(
            self.kb_collection,
            filter=f"unit_id == {int(unit_id)}",
            output_fields=["count(*)"],
        )
        return int(rows[0]["count(*)"]) if rows else 0

    # ---------- FAQ 向量 ----------

    def upsert_faq(self, faq_id: int, question: str, vector: list[float]) -> None:
        self.client.delete(self.faq_collection, filter=f"faq_id == {int(faq_id)}")
        self.client.insert(self.faq_collection, [
            {"faq_id": int(faq_id), "question": question[:1024], "embedding": vector},
        ])

    def search_faq(self, query_vector: list[float], threshold: float,
                   top_k: int = 1) -> tuple[int | None, float]:
        """返回 (faq_id|None, 相似度)；低于阈值视为未命中。"""
        res = self.client.search(
            self.faq_collection,
            data=[query_vector],
            limit=top_k,
            output_fields=["faq_id"],
            search_params={"metric_type": "COSINE", "params": {"ef": 64}},
        )
        rows = res[0] if res else []
        if not rows:
            return None, 0.0
        best = rows[0]
        score = float(best["distance"])
        if score < threshold:
            return None, score
        return int(best["entity"]["faq_id"]), score
