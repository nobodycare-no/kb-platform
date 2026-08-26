"""知识域请求模型。"""
from pydantic import BaseModel


class PermissionSetRequest(BaseModel):
    items: list[dict]   # [{target_type, target_id}]
