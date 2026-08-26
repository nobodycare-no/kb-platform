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

CORPUS: list[dict] = [
    {
        "file_name": "it_设备管理制度.md", "dept": "IT部", "perm": ("global", None),
        "content": """# IT 设备管理制度

## 设备领用
1. 新员工入职由 IT 部统一配发笔记本电脑一台，显示器一台。
2. 领用设备需在资产系统登记，签字确认。

## 设备维修
1. 设备故障请提交 IT 工单，响应时限为 4 小时。
2. 人为损坏需照价赔偿。

## 网络使用
办公网络分为办公网与访客网，访客网密码每月更换一次。""",
    },
    {
        "file_name": "hr_考勤制度.md", "dept": "HR部", "perm": ("department", None),  # None → 所属部门
        "content": """# 员工考勤制度

## 工作时间
标准工作时间为 9:00-18:00，午休 1 小时。

## 迟到与早退
1. 每月允许 2 次 10 分钟内的弹性迟到。
2. 超过 30 分钟按半天事假计。

## 请假流程
请假需提前一天在 OA 系统提交，3 天以上需部门总监审批。""",
    },
    {
        "file_name": "hr_薪酬保密制度.md", "dept": "HR部", "perm": ("department", None),
        "content": """# 薪酬保密制度

1. 员工薪酬信息属于公司机密，禁止互相打探、透露。
2. 薪酬调整结果仅由 HR 与直属负责人沟通。
3. 违反保密规定者视情节严重程度给予警告直至解除劳动合同。""",
    },
    {
        "file_name": "fin_费用报销制度.md", "dept": "财务部", "perm": ("department", None),
        "content": """# 费用报销制度

## 报销时限
费用发生后应在 5 个工作日内提交报销单。

## 发票要求
1. 必须提供增值税发票原件，抬头与税号正确。
2. 餐费报销需注明事由与参与人员名单。

## 审批层级
500 元以下部门经理审批；500-5000 元财务总监审批；5000 元以上总经理审批。""",
    },
]

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
        for name in ("IT部", "HR部", "财务部"):
            dept = db.query(Department).filter(Department.name == name).first()
            if not dept:
                dept = Department(name=name)
                db.add(dept)
                db.flush()
            depts[name] = dept

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
        pipeline = ImportPipeline(lambda: SessionLocal())
        created = 0
        for doc in CORPUS:
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
            target_id = depts[doc["dept"]].id if (target_type == "department" and raw_target is None) else raw_target
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
