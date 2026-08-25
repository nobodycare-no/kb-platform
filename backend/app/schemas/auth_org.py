"""Pydantic 请求/响应模型：认证与组织域。"""
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserInfo(BaseModel):
    id: int
    username: str
    display_name: str
    department_id: int | None = None
    is_super: bool = False


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_hours: int
    user_info: UserInfo
    permissions: list[str]


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    parent_id: int | None = None


class DepartmentOut(BaseModel):
    id: int
    parent_id: int | None
    name: str
    sort_order: int


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=64)
    display_name: str = Field(default="", max_length=64)
    department_id: int | None = None
    role_ids: list[int] = []


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=64)
    department_id: int | None = None
    status: int | None = None
    role_ids: list[int] | None = None
    password: str | None = Field(default=None, min_length=6, max_length=64)


class RoleCreate(BaseModel):
    role_name: str = Field(min_length=1, max_length=64)
    role_code: str = Field(min_length=2, max_length=64)
    description: str = ""


class RolePermissionsUpdate(BaseModel):
    permission_codes: list[str]
