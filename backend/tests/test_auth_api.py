"""认证接口集成测试（AC-01 后端部分）。"""


def test_login_ok_returns_token_and_permissions(client, users):
    resp = client.post("/api/auth/login", json={"username": "it001", "password": "Abc12345!"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["access_token"]
    assert data["expires_in_hours"] == 12
    assert data["user_info"]["username"] == "it001"
    assert data["user_info"]["department_id"] is not None
    assert "ai:chat" in data["permissions"]


def test_login_wrong_password_unified_message(client, users):
    resp = client.post("/api/auth/login", json={"username": "it001", "password": "wrong-pass"})
    assert resp.status_code == 401
    assert resp.json()["message"] == "用户名或密码错误"


def test_login_unknown_user_same_message(client, users):
    """不存在用户与密码错误提示完全一致（防用户枚举）。"""
    r1 = client.post("/api/auth/login", json={"username": "nobody", "password": "x"})
    assert r1.status_code == 401
    assert r1.json()["message"] == "用户名或密码错误"


def test_me_with_valid_token(client, users, as_user):
    resp = client.get("/api/auth/me", headers=as_user("hr001"))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["user_info"]["username"] == "hr001"
    assert "org:user:edit" in data["permissions"]


def test_me_without_token_rejected(client, users):
    assert client.get("/api/auth/me").status_code == 401


def test_superadmin_login_has_bypass_flag(client, users):
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "Abc12345!"})
    assert resp.json()["data"]["user_info"]["is_super"] is True
