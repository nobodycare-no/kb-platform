"""ORM 模型聚合出口：import 即注册全部表到 Base.metadata。

规范10表 + 工程表3（knowledge_chunks / qa_sessions / import_tasks）。
字段与 deploy/mysql/init/01_schema.sql 由 tests/test_schema_alignment.py 保证一致。
"""
from app.models.base import Base
from app.models.knowledge import ImportTask, KnowledgeChunk, KnowledgeUnit, UnitPermission
from app.models.org import Department, Role, RolePermission, User, UserRole
from app.models.qa import QaAccessLog, QaSession
from app.models.settlement import Faq, KnowledgeGap

__all__ = [
    "Base",
    "Department",
    "User",
    "Role",
    "UserRole",
    "RolePermission",
    "KnowledgeUnit",
    "KnowledgeChunk",
    "UnitPermission",
    "ImportTask",
    "QaSession",
    "QaAccessLog",
    "Faq",
    "KnowledgeGap",
]
