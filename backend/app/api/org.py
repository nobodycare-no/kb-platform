"""组织管理接口：部门树 / 用户 / 角色与权限分配。RBAC 逐端点强制。"""
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_perms
from app.core.responses import fail, ok
from app.core.security import hash_password
from app.db import get_db
from app.models import Department, Role, RolePermission, User, UserRole
from app.schemas.auth_org import (
    DepartmentCreate,
    DepartmentOut,
    RoleCreate,
    RolePermissionsUpdate,
    UserCreate,
    UserUpdate,
)

router = APIRouter(prefix="/api/org", tags=["org"])


# ---------- 部门 ----------

@router.get("/departments")
def list_departments(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    rows = db.query(Department).order_by(Department.sort_order, Department.id).all()
    items = [
        DepartmentOut(id=r.id, parent_id=r.parent_id, name=r.name, sort_order=r.sort_order).model_dump()
        for r in rows
    ]
    return ok(items)


@router.post("/departments")
def create_department(
    payload: DepartmentCreate,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_perms("org:dept:edit"))],
):
    if payload.parent_id is not None:
        if not db.query(Department).filter(Department.id == payload.parent_id).first():
            return fail(404, 4404, "父部门不存在")
    dept = Department(name=payload.name, parent_id=payload.parent_id)
    db.add(dept)
    db.commit()
    return ok(DepartmentOut(id=dept.id, parent_id=dept.parent_id, name=dept.name, sort_order=dept.sort_order).model_dump())


# ---------- 用户 ----------

def _user_dict(user: User, role_ids: list[int]) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "department_id": user.department_id,
        "status": user.status,
        "is_super": bool(user.is_super),
        "role_ids": role_ids,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _role_ids_of(db: Session, user_id: int) -> list[int]:
    return [r[0] for r in db.query(UserRole.role_id).filter(UserRole.user_id == user_id)]


@router.get("/users")
def list_users(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_perms("org:user:view"))],
    keyword: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    q = db.query(User)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(User.username.like(like) | User.display_name.like(like))
    total = q.count()
    rows = q.order_by(User.id).offset((page - 1) * page_size).limit(page_size).all()
    return ok({"total": total, "items": [_user_dict(u, _role_ids_of(db, u.id)) for u in rows]})


@router.post("/users")
def create_user(
    payload: UserCreate,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_perms("org:user:edit"))],
):
    if db.query(User).filter(User.username == payload.username).first():
        return fail(409, 4309, "用户名已存在")
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name or payload.username,
        department_id=payload.department_id,
        status=1,
    )
    db.add(user)
    db.flush()
    for rid in dict.fromkeys(payload.role_ids):
        db.add(UserRole(user_id=user.id, role_id=rid))
    db.commit()
    return ok(_user_dict(user, _role_ids_of(db, user.id)))


@router.put("/users/{user_id}")
def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_perms("org:user:edit"))],
):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return fail(404, 4404, "用户不存在")
    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.department_id is not None:
        user.department_id = payload.department_id
    if payload.status is not None:
        if payload.status not in (0, 1):
            return fail(400, 4400, "status 仅允许 0/1")
        user.status = payload.status
    if payload.password:
        user.password_hash = hash_password(payload.password)
    if payload.role_ids is not None:
        db.query(UserRole).filter(UserRole.user_id == user_id).delete()
        for rid in dict.fromkeys(payload.role_ids):
            db.add(UserRole(user_id=user_id, role_id=rid))
    db.commit()
    return ok(_user_dict(user, _role_ids_of(db, user_id)))


# ---------- 角色与权限 ----------

def _role_dict(role: Role, codes: list[str]) -> dict:
    return {
        "id": role.id,
        "role_name": role.role_name,
        "role_code": role.role_code,
        "description": role.description,
        "permission_codes": codes,
    }


@router.get("/roles")
def list_roles(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    roles = db.query(Role).order_by(Role.id).all()
    perms = {}
    for r in db.query(RolePermission).all():
        perms.setdefault(r.role_id, []).append(r.permission_code)
    return ok([_role_dict(r, sorted(perms.get(r.id, []))) for r in roles])


@router.post("/roles")
def create_role(
    payload: RoleCreate,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_perms("org:role:edit"))],
):
    if db.query(Role).filter(Role.role_code == payload.role_code).first():
        return fail(409, 4309, "角色编码已存在")
    role = Role(role_name=payload.role_name, role_code=payload.role_code, description=payload.description)
    db.add(role)
    db.commit()
    return ok(_role_dict(role, []))


@router.put("/roles/{role_id}/permissions")
def update_role_permissions(
    role_id: int,
    payload: RolePermissionsUpdate,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_perms("org:role:edit"))],
):
    role = db.query(Role).filter(Role.id == role_id).first()
    if role is None:
        return fail(404, 4404, "角色不存在")
    db.query(RolePermission).filter(RolePermission.role_id == role_id).delete()
    for code in dict.fromkeys(payload.permission_codes):
        db.add(RolePermission(role_id=role_id, permission_code=code, permission_type="api"))
    db.commit()
    codes = [r[0] for r in db.query(RolePermission.permission_code).filter(RolePermission.role_id == role_id)]
    return ok({"id": role_id, "permission_codes": sorted(codes)})
