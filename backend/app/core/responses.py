"""统一响应包 {code, message, data}（SDD §5 约定）。"""
from typing import Any


def ok(data: Any = None, message: str = "ok") -> dict:
    return {"code": 0, "message": message, "data": data}


def err(code: int, message: str, data: Any = None) -> dict:
    return {"code": code, "message": message, "data": data}
