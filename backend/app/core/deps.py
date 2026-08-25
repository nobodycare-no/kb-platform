"""FastAPI 依赖：当前用户解析（JWT）、操作权限校验。

约定：校验失败抛 ApiError，由 main.py 注册的全局异常处理器转为
统一响应包 {code,message,data}；成功返回 User 实体。
"""
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.security import JWTError, decode_token
from app.db import get_db
from app.models import User
from app.services.permission_service import PermissionService


def resolve_user(request: Request, db: Session) -> User:
    """从 Authorization: Bearer 解析并加载启用用户；失败抛 ApiError(401)。"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise ApiError(401, 4101, "未登录或令牌缺失")
    token = auth[len("Bearer "):].strip()
    try:
        claims = decode_token(token, get_settings().jwt_secret)
    except JWTError:
        raise ApiError(401, 4101, "登录状态无效，请重新登录") from None
    user = db.query(User).filter(User.id == claims.sub).first()
    if user is None or user.status != 1:
        raise ApiError(401, 4101, "登录状态无效，请重新登录")
    return user


def require_perms(*codes: str) -> Callable:
    """RBAC 校验依赖工厂；超管旁路。用法：Depends(require_perms("org:user:edit"))。"""

    def dependency(
        request: Request,
        db: Annotated[Session, Depends(get_db)],
    ) -> User:
        user = resolve_user(request, db)
        if user.is_super:
            return user
        have = set(PermissionService(db).permission_codes(user.id))
        if not have.intersection(codes):
            raise ApiError(403, 4303, "无权执行该操作", {"required": list(codes)})
        return user

    return dependency


def get_current_user(request: Request, db: Annotated[Session, Depends(get_db)]) -> User:
    """仅认证不鉴权的标准依赖。"""
    return resolve_user(request, db)
