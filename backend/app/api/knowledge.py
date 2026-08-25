"""知识维护接口（SRD FR-B / AC-02）：批量导入、进度轮询、知识单元 CRUD。"""
import hashlib
import threading
import uuid
from datetime import datetime
from typing import Annotated, List

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_perms
from app.core.errors import ApiError
from app.core.responses import fail, ok
from app.db import get_db
from app.models import ImportTask, KnowledgeChunk, KnowledgeUnit, User
from app.services.chunker import chunk_text
from app.services.import_pipeline import ImportPipeline, save_blob
from app.services.parsers import ALLOWED_EXTENSIONS, MAX_SIZE_BYTES

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

MAX_FILES_PER_BATCH = 20


def get_import_pipeline(request: Request) -> ImportPipeline:
    """优先取测试注入的 app.state.import_pipeline，否则按环境配置构造单例。"""
    pipeline = getattr(request.app.state, "import_pipeline", None)
    if pipeline is not None:
        return pipeline
    if not hasattr(request.app.state, "_import_pipeline_default"):
        from app.db import SessionLocal
        request.app.state._import_pipeline_default = ImportPipeline(SessionLocal)
    return request.app.state._import_pipeline_default


def _ext(filename: str) -> str:
    dot = filename.rfind(".")
    return filename[dot + 1:].lower()[:15] if dot >= 0 else ""


# ---------- 批量导入 ----------

@router.post("/import")
async def import_documents(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_perms("kb:unit:edit"))],
    files: List[UploadFile] = File(...),
):
    _ = user
    if not files:
        raise ApiError(400, 4400, "未收到任何文件")
    if len(files) > MAX_FILES_PER_BATCH:
        raise ApiError(400, 4400, f"单次最多 {MAX_FILES_PER_BATCH} 个文件")

    saved: list[tuple[str, bytes]] = []
    for f in files:
        data = await f.read()
        if not any(f.filename.lower().endswith(e) for e in ALLOWED_EXTENSIONS):
            return fail(400, 4400, f"不支持的文件类型: {f.filename}（允许 {sorted(ALLOWED_EXTENSIONS)}）")
        if len(data) > MAX_SIZE_BYTES:
            return fail(400, 4400, f"文件超过 20MB 上限: {f.filename}")
        saved.append((f.filename, data))

    pipeline = get_import_pipeline(request)
    batch_no = uuid.uuid4().hex[:32]

    task_ids: list[int] = []
    for filename, data in saved:
        task = ImportTask(batch_no=batch_no, file_name=filename,
                          file_type=_ext(filename), size_bytes=len(data))
        db.add(task)
        db.flush()
        save_blob(batch_no, task.id, data)   # blob 落盘供后台线程读取
        task_ids.append(task.id)
    db.commit()

    inline = getattr(request.app.state, "import_inline", False)
    for tid in task_ids:
        if inline:
            pipeline.process(tid)          # 测试/调试：同步确定性
        else:
            threading.Thread(target=pipeline.process, args=(tid,), daemon=True).start()

    rows = db.query(ImportTask).filter(ImportTask.id.in_(task_ids)).all()
    by_id = {r.id: r for r in rows}
    return ok({
        "batch_no": batch_no,
        "tasks": [{"task_id": tid, "file_name": by_id[tid].file_name,
                   "status": by_id[tid].task_status} for tid in task_ids],
    })


@router.get("/import/tasks")
def import_task_status(
    ids: Annotated[str, Query(description="逗号分隔的 task id")],
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    try:
        id_list = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise ApiError(400, 4400, "ids 格式错误") from None
    rows = db.query(ImportTask).filter(ImportTask.id.in_(id_list)).all()
    return ok([{"task_id": r.id, "file_name": r.file_name,
                "status": r.task_status, "error_message": r.error_message,
                "unit_id": r.unit_id} for r in rows])


# ---------- 知识单元 ----------

def _unit_brief(u: KnowledgeUnit) -> dict:
    return {"id": u.id, "unit_code": u.unit_code, "title": u.title,
            "category": u.category, "summary": u.summary, "status": u.status,
            "file_type": u.file_type,
            "created_at": u.created_at.isoformat() if u.created_at else None}


@router.get("/units")
def list_units(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    keyword: str = "",
    category: str = "",
    status: int | None = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    q = db.query(KnowledgeUnit)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(KnowledgeUnit.title.like(like) | KnowledgeUnit.content.like(like))
    if category:
        q = q.filter(KnowledgeUnit.category == category)
    if status is not None:
        q = q.filter(KnowledgeUnit.status == status)
    total = q.count()
    rows = q.order_by(KnowledgeUnit.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return ok({"total": total, "items": [_unit_brief(u) for u in rows]})


@router.get("/units/{unit_id}")
def get_unit(
    unit_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    u = db.query(KnowledgeUnit).filter(KnowledgeUnit.id == unit_id).first()
    if u is None:
        raise ApiError(404, 4404, "知识单元不存在")
    chunk_count = db.query(KnowledgeChunk).filter(KnowledgeChunk.unit_id == unit_id).count()
    data = _unit_brief(u)
    data.update({"content": u.content, "source_file_name": u.source_file_name,
                 "chunk_count": chunk_count})
    return ok(data)


@router.put("/units/{unit_id}")
def update_unit(
    unit_id: int,
    payload: dict,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_perms("kb:unit:edit"))],
):
    u = db.query(KnowledgeUnit).filter(KnowledgeUnit.id == unit_id).first()
    if u is None:
        raise ApiError(404, 4404, "知识单元不存在")

    for field in ("title", "category", "summary"):
        if payload.get(field) is not None:
            setattr(u, field, str(payload[field])[:512])
    if payload.get("status") is not None:
        if payload["status"] not in (0, 1):
            raise ApiError(400, 4400, "status 仅允许 0/1")
        u.status = payload["status"]

    content_changed = bool(payload.get("content")) and payload["content"] != u.content
    chunks: list = []
    if content_changed:
        u.content = payload["content"]
        chunks = chunk_text(u.content)
        db.query(KnowledgeChunk).filter(KnowledgeChunk.unit_id == unit_id).delete()
        db.add_all([
            KnowledgeChunk(unit_id=u.id, seq_no=c.seq_no, content=c.text,
                           content_hash=hashlib.sha256(c.text.encode()).hexdigest())
            for c in chunks
        ])
    db.commit()

    reindexed = False
    if content_changed:
        pipeline = get_import_pipeline(request)
        pipeline.index_chunks(u.id, [(c.seq_no, c.text) for c in chunks])
        reindexed = True

    return ok({"id": u.id, "title": u.title, "status": u.status, "reindexed": reindexed})


@router.delete("/units/{unit_id}")
def delete_unit(
    unit_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_perms("kb:unit:edit"))],
):
    u = db.query(KnowledgeUnit).filter(KnowledgeUnit.id == unit_id).first()
    if u is None:
        raise ApiError(404, 4404, "知识单元不存在")
    # 先清向量索引；失败则整体失败保持可重试（ADR-003）
    get_import_pipeline(request).delete_index(unit_id)
    db.query(KnowledgeChunk).filter(KnowledgeChunk.unit_id == unit_id).delete()
    db.delete(u)
    db.commit()
    return ok({"deleted": unit_id})
