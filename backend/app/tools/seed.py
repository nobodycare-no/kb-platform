"""演示数据种子脚本（FR-G03）：一键初始化部门/角色/用户/知识库/权限矩阵。

用法（backend 容器内）：
    python -m app.tools.seed            # 幂等，可重复执行
    python -m app.tools.seed --reindex  # 同时全量重建向量索引

权限矩阵设计：
  - IT 制度   → global 公开（所有人可见）
  - HR 制度   → 仅 HR 部门
  - 财务制度  → 仅 财务部 + 管理层角色(kb_admin)
"""
from __future__ import annotations

import sys

from app.core.security import hash_password
from app.db import SessionLocal
from app.models import (Department, KnowledgeChunk, KnowledgeUnit,
                        Role, RolePermission, UnitPermission, User, UserRole)
from app.services.import_pipeline import ImportPipeline

PASSWORD = "Abc12345!"

# 语料目录：deploy/seed/corpus/*.md
# 文件名前缀 → 部门与权限映射（展示四种权限实体中的三种 + 角色）：
#   it_    → IT部   全局公开
#   hr_    → HR部   仅本部门
#   fin_   → 财务部  仅本部门
#   admin_ → 行政部  全局公开
#   mgmt_  → 管理层角色(kb_admin) 可见 —— 演示「角色」维度
import os
from pathlib import Path

CORPUS_DIR = Path(os.getenv(
    "SEED_CORPUS_DIR",
    str(Path(__file__).resolve().parents[3] / "deploy" / "seed" / "corpus"),
))

PERM_RULES = {
    "it_":    ("IT部",   ("global", None)),
    "hr_":    ("HR部",   ("department", "HR部")),
    "fin_":   ("财务部",  ("department", "财务部")),
    "admin_": ("行政部", ("global", None)),
    "mgmt_":  ("IT部",   ("role", "kb_admin")),       # 文档归属 IT 部但按角色放行
}


def load_corpus() -> list[dict]:
    """优先读取语料目录；目录缺失时回退到内置最小集。"""
    docs: list[dict] = []
    if CORPUS_DIR.exists():
        for path in sorted(CORPUS_DIR.glob("*.md")):
            prefix = next((p for p in PERM_RULES if path.name.startswith(p)), None)
            if prefix is None:
                continue
            dept, perm = PERM_RULES[prefix]
            docs.append({"file_name": path.name, "dept": dept,
                         "perm": perm, "content": path.read_text(encoding="utf-8")})
    return docs


CORPUS: list[dict] = []

ROLES = {
    "kb_admin": ("知识管理员", ["ai:chat", "kb:unit:edit", "kb:import",
                                "org:user:view", "settle:review", "dash:view"]),
    "asker": ("提问者", ["ai:chat", "dash:view"]),
}

USERS = [
    ("admin", "超管", None, True, []),
    ("hr001", "HR 小李", "HR部", False, ["kb_admin"]),
    ("it001", "IT 小王", "IT部", False, ["asker"]),
    ("fin001", "财务小张", "财务部", False, ["asker"]),
]


def run(reindex: bool) -> None:
    db = SessionLocal()
    try:
        # ---- 部门 ----
        depts: dict[str, Department] = {}
        for name in ("IT部", "HR部", "财务部", "行政部"):
            dept = db.query(Department).filter(Department.name == name).first()
            if not dept:
                dept = Department(name=name)
                db.add(dept)
                db.flush()
            depts[name] = dept

        def _to_target(target_type: str, raw):
            if target_type == "department":
                return depts[raw].id
            if target_type == "role":
                return roles[raw].id
            return raw  # global → None

        # ---- 角色 ----
        roles: dict[str, Role] = {}
        for code, (name, perms) in ROLES.items():
            role = db.query(Role).filter(Role.role_code == code).first()
            if not role:
                role = Role(role_name=name, role_code=code)
                db.add(role)
                db.flush()
            for perm in perms:
                exists = db.query(RolePermission).filter_by(
                    role_id=role.id, permission_code=perm).first()
                if not exists:
                    db.add(RolePermission(role_id=role.id, permission_code=perm))
            roles[code] = role
        db.flush()

        # ---- 用户 ----
        for username, display, dept_name, is_super, role_codes in USERS:
            user = db.query(User).filter(User.username == username).first()
            if not user:
                user = User(username=username, password_hash=hash_password(PASSWORD),
                            display_name=display, department_id=None, is_super=int(is_super))
                db.add(user)
                db.flush()
            if dept_name and not user.department_id:
                user.department_id = depts[dept_name].id
            for rc in role_codes:
                link_exists = db.query(UserRole).filter_by(
                    user_id=user.id, role_id=roles[rc].id).first()
                if not link_exists:
                    db.add(UserRole(user_id=user.id, role_id=roles[rc].id))
        db.commit()

        # ---- 知识单元 ----
        docs = load_corpus()
        print(f"[seed] 语料目录载入 {len(docs)} 篇: {[d['file_name'] for d in docs]}")
        if not docs:
            print("[hint] 检查 SEED_CORPUS_DIR 环境变量或 compose 卷挂载")
        pipeline = ImportPipeline(lambda: SessionLocal())
        created = 0
        for doc in docs:
            unit_code = "SEED-" + doc["file_name"]
            if db.query(KnowledgeUnit).filter(KnowledgeUnit.unit_code == unit_code).first():
                continue

            unit = KnowledgeUnit(
                unit_code=unit_code,
                title=doc["file_name"].rsplit(".", 1)[0],
                content=doc["content"],
                summary=doc["content"][:100],
                category=doc["dept"],
                source_file_name=doc["file_name"],
                file_type="md", status=1,
            )
            db.add(unit)
            db.flush()

            from app.services.chunker import chunk_text
            chunks = chunk_text(doc["content"], is_markdown=True)
            db.add_all([
                KnowledgeChunk(unit_id=unit.id, seq_no=c.seq_no, content=c.text,
                               content_hash=__import__("hashlib").sha256(c.text.encode()).hexdigest())
                for c in chunks
            ])
            target_type, raw_target = doc["perm"]
            target_id = _to_target(target_type, raw_target or doc["dept"])
            db.add(UnitPermission(unit_id=unit.id, target_type=target_type, target_id=target_id))
            db.commit()

            vectors_needed = [(c.seq_no, c.text) for c in chunks]
            try:
                pipeline.index_chunks(unit.id, vectors_needed)
                print(f"[seed] 已索引 {doc['file_name']} ({len(vectors_needed)} 片)")
            except Exception as e:
                print(f"[warn] {doc['file_name']} 向量索引失败（ai-service 未就绪？）：{e}")
                print("       可稍后执行 python -m app.tools.reindex 补建")
            created += 1

        print(f"[done] 种子完成：新增知识单元 {created} 个；账号 admin/hr001/it001/fin001 密码 {PASSWORD}")

        if reindex:
            from app.tools.reindex import reindex_all
            reindex_all(db)
    finally:
        db.close()


if __name__ == "__main__":
    run(reindex="--reindex" in sys.argv)
