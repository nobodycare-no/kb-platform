"""批量导入管线（SRD FR-B01~B05）：解析→切片→正本入库→向量化索引。

状态机：pending → parsing → embedding → done | failed(error_message)
写路径顺序：MySQL 事务先行（事实源），Milvus 经 ai-service 内部端点索引；
索引失败任务标 failed 可重试（ADR-003）。
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime
from typing import Callable, Sequence

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ImportTask, KnowledgeChunk, KnowledgeUnit
from app.services.chunker import chunk_text
from app.services.parsers import extract_text


def new_batch_no() -> str:
    return uuid.uuid4().hex[:32]


class ImportPipeline:
    """每个应用实例持有一个；测试可注入 transport 与 spawn=False 内联执行。"""

    def __init__(self, db_factory: Callable[[], Session], *,
                 ai_base_url: str | None = None, internal_token: str | None = None,
                 transport: httpx.BaseTransport | None = None,
                 chunk_size: int = 500, chunk_overlap: int = 50):
        self._db_factory = db_factory
        self._ai_base = (ai_base_url or get_settings().ai_service_base_url).rstrip("/")
        self._token = internal_token if internal_token is not None else get_settings().internal_token
        self._client = httpx.Client(transport=transport) if transport else httpx.Client()
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    # ---------- 提交 ----------

    def submit(self, files: Sequence[tuple[str, bytes]], *, batch_no: str | None = None,
               spawn: bool = True) -> list[int]:
        batch = batch_no or new_batch_no()
        task_ids: list[int] = []
        db = self._db_factory()
        try:
            for filename, data in files:
                task = ImportTask(batch_no=batch, file_name=filename,
                                  file_type=_safe_ext(filename), size_bytes=len(data))
                db.add(task)
                db.flush()
                task_ids.append(task.id)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        for tid in task_ids:
            if spawn:
                threading.Thread(target=self.process, args=(tid,), daemon=True).start()
            else:
                self.process(tid)
        return task_ids

    # ---------- 处理 ----------

    def process(self, task_id: int) -> None:
        db = self._db_factory()
        try:
            task = db.query(ImportTask).filter(ImportTask.id == task_id).one()
            try:
                unit_id = self._process_inner(db, task)
                task.task_status = "done"
                task.unit_id = unit_id
                task.finished_at = datetime.now()
                db.commit()
            except Exception as e:
                db.rollback()
                task.task_status = "failed"
                task.error_message = str(e)[:500]
                task.finished_at = datetime.now()
                db.commit()
        finally:
            db.close()

    def _process_inner(self, db: Session, task: ImportTask) -> int:
        data = _load_file_bytes(task)

        task.task_status = "parsing"
        db.commit()
        text, file_type = extract_text(data, task.file_name)
        chunks = chunk_text(text, is_markdown=file_type == "md",
                            size=self._chunk_size, overlap=self._chunk_overlap)

        unit = KnowledgeUnit(
            unit_code=f"U{datetime.now():%Y%m%d}{uuid.uuid4().hex[:8]}",
            title=_title_from_filename(task.file_name),
            content=text,
            summary=text[:100],
            category="",
            source_file_name=task.file_name,
            file_type=file_type,
            status=1,
        )
        db.add(unit)
        db.flush()
        db.add_all([KnowledgeChunk(unit_id=unit.id, seq_no=c.seq_no,
                                   content=c.text,
                                   content_hash=__import__("hashlib").sha256(c.text.encode()).hexdigest())
                    for c in chunks])
        task.file_type = file_type
        db.commit()

        task.task_status = "embedding"
        db.commit()
        self._index_remote(unit.id, [(c.seq_no, c.text) for c in chunks])
        return unit.id

    def _index_remote(self, unit_id: int, items: list[tuple[int, str]]) -> None:
        resp = self._client.post(
            f"{self._ai_base}/internal/kb/index",
            headers={"X-Internal-Token": self._token},
            json={"unit_id": unit_id, "chunks": [{"seq": s, "text": t} for s, t in items]},
            timeout=httpx.Timeout(5, read=120, write=60),
        )
        if resp.status_code != 200:
            raise RuntimeError(f"向量索引失败 HTTP {resp.status_code}: {resp.text[:200]}")

    def index_chunks(self, unit_id: int, items: list[tuple[int, str]]) -> None:
        """公开别名：整单元替换式索引（更新内容时复用）。"""
        self._index_remote(unit_id, items)

    def delete_index(self, unit_id: int) -> None:
        resp = self._client.delete(
            f"{self._ai_base}/internal/kb/unit/{int(unit_id)}",
            headers={"X-Internal-Token": self._token},
            timeout=httpx.Timeout(5, read=30),
        )
        if resp.status_code != 200:
            raise RuntimeError(f"向量清理失败 HTTP {resp.status_code}: {resp.text[:200]}")


def _safe_ext(filename: str) -> str:
    dot = filename.rfind(".")
    return filename[dot + 1:].lower()[:15] if dot >= 0 else ""


def _title_from_filename(filename: str) -> str:
    stem = filename.rsplit("/", 1)[-1]
    dot = stem.rfind(".")
    return stem[:dot] if dot > 0 else stem


def _load_file_bytes(task: ImportTask) -> bytes:
    """开发期上传文件暂存于 uploads/{batch}/{task}.bin（见 api/knowledge.py 落盘）。"""
    path = _task_blob_path(task.batch_no, task.id)
    with open(path, "rb") as f:
        return f.read()


def _task_blob_path(batch_no: str, task_id: int) -> str:
    import os
    root = os.getenv("UPLOAD_DIR", "uploads")
    os.makedirs(root, exist_ok=True)
    return os.path.join(root, f"{batch_no}_{task_id}.bin")


def save_blob(batch_no: str, task_id: int, data: bytes) -> str:
    path = _task_blob_path(batch_no, task_id)
    with open(path, "wb") as f:
        f.write(data)
    return path
