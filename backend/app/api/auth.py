"""认证接口：登录签发 JWT、当前用户信息。"""
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import resolve_user
from app.core.responses import fail, ok
from app.core.security import create_token, verify_password
from app.db import get_db
from app.models import User
from app.schemas.auth_org import LoginRequest, LoginResponse, UserInfo
from app.services.permission_service import PermissionService

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_payload(user: User, codes: list[str]) -> dict:
    return {
        "user_info": UserInfo(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            department_id=user.department_id,
            is_super=bool(user.is_super),
        ).model_dump(),
        "permissions": codes,
    }


@router.post("/login")
def login(payload: LoginRequest, db: Annotated[Session, Depends(get_db)]):
    user = db.query(User).filter(User.username == payload.username).first()
    # 统一模糊提示，不区分"用户不存在/密码错误"（NFR-03）
    if user is None or not verify_password(payload.password, user.password_hash):
        return fail(401, 4101, "用户名或密码错误")
    if user.status != 1:
        return fail(403, 4301, "账号已停用，请联系管理员")

    from app.core.redis_client import get_redis

    svc = PermissionService(db, redis_client=get_redis())
    body = _user_payload(user, svc.permission_codes(user.id))
    settings = get_settings()
    token = create_token(
        sub=user.id,
        username=user.username,
        department_id=user.department_id,
        role_ids=sorted(svc.user_ctx(user_id=user.id, department_id=user.department_id).role_ids),
        permission_codes=body["permissions"],
        secret=settings.jwt_secret,
        expire_hours=settings.jwt_expire_hours,
    )
    resp = LoginResponse(
        access_token=token,
        expires_in_hours=settings.jwt_expire_hours,
        **body,
    )
    return ok(resp.model_dump())


@router.get("/me")
def me(request: Request, db: Annotated[Session, Depends(get_db)]):
    user: User = resolve_user(request, db)
    from app.core.redis_client import get_redis

    return ok(_user_payload(user, PermissionService(db, redis_client=get_redis()).permission_codes(user.id)))
