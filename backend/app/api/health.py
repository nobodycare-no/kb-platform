from fastapi import APIRouter

from app.core.responses import ok

router = APIRouter(tags=["meta"])


@router.get("/health")
def health() -> dict:
    """进程级存活探针（依赖级自检在 ai-service 的 /health/models）。"""
    return ok({"status": "up"})
