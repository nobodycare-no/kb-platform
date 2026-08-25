"""统一响应包 {code, message, data}（SDD §5 约定）。"""
from typing import Any

from fastapi.responses import JSONResponse


def ok(data: Any = None, message: str = "ok") -> dict:
    return {"code": 0, "message": message, "data": data}


def err(code: int, message: str, data: Any = None) -> dict:
    return {"code": code, "message": message, "data": data}


def fail(status_code: int, code: int, message: str) -> JSONResponse:
    """带 HTTP 状态码的业务失败（保持统一响应包）。"""
    return JSONResponse(status_code=status_code, content=err(code, message))
