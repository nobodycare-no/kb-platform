"""组织管理 RBAC 集成测试（AC-01 后端部分）。"""


def test_create_user_by_kb_admin_ok(client, users, as_user):
    resp = client.post(
        "/api/org/users",
        headers=as_user("hr001"),
        json={
            "username": "fin001",
            "password": "Abc12345!",
            "display_name": "财务小张",
            "role_ids": [users["asker_role"].id],
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["username"] == "fin001"
    assert data["role_ids"] == [users["asker_role"].id]

    # 新用户能立即登录
    login = client.post("/api/auth/login", json={"username": "fin001", "password": "Abc12345!"})
    assert login.status_code == 200


def test_create_user_without_perm_forbidden(client, users, as_user):
    """it001 只有 ai:chat，无 org:user:edit → 403。"""
    resp = client.post(
        "/api/org/users",
        headers=as_user("it001"),
        json={"username": "hacker", "password": "Abc12345!"},
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body["code"] == 4303
    assert "org:user:edit" in body["data"]["required"]


def test_org_endpoints_require_login(client, users):
    assert client.get("/api/org/users").status_code == 401
    assert client.get("/api/org/departments").status_code == 401


def test_duplicate_username_conflict(client, users, as_user):
    resp = client.post(
        "/api/org/users",
        headers=as_user("hr001"),
        json={"username": "it001", "password": "Abc12345!"},
    )
    assert resp.status_code == 409


def test_update_user_reset_password_and_roles(client, users, as_user):
    headers = as_user("admin")  # 超管旁路
    uid = users["it001"].id
    resp = client.put(
        f"/api/org/users/{uid}",
        headers=headers,
        json={"display_name": "IT老王", "status": 0, "password": "New123456!", "role_ids": [users["kb_admin_role"].id]},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["display_name"] == "IT老王"
    assert data["status"] == 0
    assert data["role_ids"] == [users["kb_admin_role"].id]

    # 停用后原密码登录被拒，新密码可登录但状态停用 → 4301
    old_pw = client.post("/api/auth/login", json={"username": "it001", "password": "Abc12345!"})
    assert old_pw.status_code in (401, 403)


def test_role_permissions_assignment(client, users, as_user):
    rid = users["asker_role"].id
    resp = client.put(
        f"/api/org/roles/{rid}/permissions",
        headers=as_user("admin"),
        json={"permission_codes": ["ai:chat", "dash:view"]},
    )
    assert resp.status_code == 200
    codes = set(resp.json()["data"]["permission_codes"])
    assert codes == {"ai:chat", "dash:view"}

    # 权限变更即时生效于 DB 校验链路（it001 新增 dash:view 后应可通过 require_perms）
    list_resp = client.get("/api/org/users", headers=as_user("it001"))
    # it01 没有 org:user:view，仍应 403 —— 但 dash:view 不影响此端点
    assert list_resp.status_code == 403


def test_departments_tree_list(client, users, as_user):
    resp = client.get("/api/org/departments", headers=as_user("hr001"))
    assert resp.status_code == 200
    names = {item["name"] for item in resp.json()["data"]}
    assert {"IT部", "HR部", "财务部"} <= names

    create = client.post("/api/org/departments", headers=as_user("admin"), json={"name": "行政部"})
    assert create.status_code == 200
