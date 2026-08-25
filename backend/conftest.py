"""pytest 全局夹具：SQLite 内存库替代 MySQL（ORM 全为可移植类型），种子数据齐备。

放在 backend/ 根目录使 `app` 包可导入。
"""
import os

os.environ.setdefault("JWT_SECRET", "unit-test-secret")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("MYSQL_URL", "sqlite://")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import httpx  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db import get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    Department,
    Role,
    RolePermission,
    User,
    UserRole,
)

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

PASSWORD = "Abc12345!"


@pytest.fixture()
def db():
    """每测试独立内存库：建表→用完销毁。"""
    Base.metadata.create_all(engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def users(db):
    """种子：3部门 + admin(超管)/hr001(知识管理员)/it001(提问者)。"""
    it, hr, fin = Department(name="IT部"), Department(name="HR部"), Department(name="财务部")
    db.add_all([it, hr, fin])
    db.flush()

    admin = User(username="admin", password_hash=hash_password(PASSWORD), display_name="超管", is_super=1)
    kb_admin_role = Role(role_name="知识管理员", role_code="kb_admin")
    asker_role = Role(role_name="提问者", role_code="asker")
    hr001 = User(username="hr001", password_hash=hash_password(PASSWORD), display_name="HR小李", department_id=hr.id)
    it001 = User(username="it001", password_hash=hash_password(PASSWORD), display_name="IT小王", department_id=it.id)
    db.add_all([admin, kb_admin_role, asker_role, hr001, it001])
    db.flush()

    db.add_all([
        UserRole(user_id=hr001.id, role_id=kb_admin_role.id),
        UserRole(user_id=it001.id, role_id=asker_role.id),
        RolePermission(role_id=kb_admin_role.id, permission_code="org:user:view"),
        RolePermission(role_id=kb_admin_role.id, permission_code="org:user:edit"),
        RolePermission(role_id=kb_admin_role.id, permission_code="kb:unit:edit"),
        RolePermission(role_id=asker_role.id, permission_code="ai:chat"),
    ])
    db.commit()
    return {"admin": admin, "hr001": hr001, "it001": it001, "kb_admin_role": kb_admin_role, "asker_role": asker_role}


@pytest.fixture()
def client(db):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


@pytest.fixture()
def ais_stub(db, tmp_path, monkeypatch):
    """导入管线测试桩：Mock 捕获 ai-service 的索引/删除调用；blob 写入临时目录。"""
    import json as _json

    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    calls = {"index": [], "delete": []}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/internal/kb/index"):
            body = _json.loads(request.content)
            calls["index"].append(body)
            return httpx.Response(200, json={"indexed": len(body["chunks"])})
        if "/internal/kb/unit/" in path:
            calls["delete"].append(int(path.rsplit("/", 1)[-1]))
            return httpx.Response(200, json={"deleted": 1})
        return httpx.Response(404, json={})

    from app.services.import_pipeline import ImportPipeline

    pipeline = ImportPipeline(
        lambda: TestingSession(),
        ai_base_url="http://ais-stub",
        internal_token="stub-token",
        transport=httpx.MockTransport(handler),
    )

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.state.import_pipeline = pipeline
    app.state.import_inline = True       # 测试：同步处理保证确定性
    client = TestClient(app)
    client.ais_calls = calls          # type: ignore[attr-defined]
    return client


@pytest.fixture()
def as_user(client, users):
    """as_user("hr001") -> 带 Bearer 的请求头。"""

    def _make(username: str) -> dict[str, str]:
        resp = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
        assert resp.status_code == 200, resp.text
        token = resp.json()["data"]["access_token"]
        return {"Authorization": f"Bearer {token}"}

    return _make
