"""内部调用守卫：X-Internal-Token 常量时间比较。"""
import hmac

from fastapi import Request

from app.core.config import get_settings
from app.core.errors import ApiError


def verify_internal_token(request: Request) -> None:
    token = request.headers.get("X-Internal-Token", "")
    if not hmac.compare_digest(token, get_settings().internal_token):
        raise ApiError(401, 4101, "invalid internal token")


def has_internal_token(request: Request) -> bool:
    token = request.headers.get("X-Internal-Token", "")
    return hmac.compare_digest(token, get_settings().internal_token)
