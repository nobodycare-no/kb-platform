"""导入管线集成测试（AC-02）：部分成功、进度轮询、向量索引调用、权限。"""
import time


def wait_terminal(client, headers, task_ids: list[int], timeout: float = 10.0) -> list[dict]:
    deadline = time.time() + timeout
    data = []
    while time.time() < deadline:
        resp = client.get("/api/knowledge/import/tasks",
                          params={"ids": ",".join(map(str, task_ids))},
                          headers=headers)
        body = resp.json()
        data = body.get("data") or []
        if data and all(t["status"] in ("done", "failed") for t in data):
            return sorted(data, key=lambda t: t["task_id"])
        time.sleep(0.15)
    return sorted(data, key=lambda t: t["task_id"])


def _upload(client, headers, files: list[tuple[str, bytes]]):
    return client.post(
        "/api/knowledge/import",
        headers=headers,
        files=[("files", (name, data, "application/octet-stream")) for name, data in files],
    )


def test_import_partial_success_and_units_created(ais_stub, users, as_user):
    files = [
        ("it运维制度.md", ("# 设备管理\n" + "机房设备每季度巡检一次。" * 40).encode()),
        ("报销说明.txt", "费用报销需在 5 个工作日内提交发票。".encode()),
        ("broken.pdf", b"%PDF-1.4 this is not a real pdf body"),
    ]
    resp = _upload(ais_stub, as_user("hr001"), files)
    assert resp.status_code == 200, resp.text
    batch = resp.json()["data"]
    ids = [t["task_id"] for t in batch["tasks"]]
    assert len(ids) == 3

    results = wait_terminal(ais_stub, as_user("hr001"), ids)
    statuses = {t["status"] for t in results}
    assert statuses == {"done", "failed"}, results

    failed = next(t for t in results if t["status"] == "failed")
    assert "PDF 解析失败" in failed["error_message"] or "未能" in failed["error_message"]

    done_units = [t["unit_id"] for t in results if t["status"] == "done"]
    assert all(done_units)

    # ai-service 的索引端点被调用了两次（两个成功文件），且带内部令牌头
    assert len(ais_stub.ais_calls["index"]) == 2
    indexed_unit_ids = {c["unit_id"] for c in ais_stub.ais_calls["index"]}
    assert indexed_unit_ids == set(done_units)


def test_import_requires_kb_edit_permission(ais_stub, users, as_user):
    resp = _upload(ais_stub, as_user("it001"),
                   [("x.txt", b"hello")])
    assert resp.status_code == 403


def test_import_unsupported_extension_400(ais_stub, users, as_user):
    resp = _upload(ais_stub, as_user("hr001"), [("bad.exe", b"MZ")])
    assert resp.status_code == 400
    assert "不支持的文件类型" in resp.json()["message"]


def test_unit_lifecycle_with_index_cleanup(ais_stub, users, as_user):
    resp = _upload(ais_stub, as_user("hr001"), [("tmp.md", "# T\n正文内容。".encode())])
    ids = [t["task_id"] for t in resp.json()["data"]["tasks"]]
    results = wait_terminal(ais_stub, as_user("admin"), ids)
    unit_id = results[0]["unit_id"]

    # 详情可见切片数
    detail = ais_stub.get(f"/api/knowledge/units/{unit_id}", headers=as_user("admin"))
    assert detail.status_code == 200
    assert detail.json()["data"]["chunk_count"] >= 1

    # 删除 → 调用 ai-service 清理 + DB 移除
    deleted = ais_stub.delete(f"/api/knowledge/units/{unit_id}", headers=as_user("admin"))
    assert deleted.status_code == 200
    assert ais_stub.ais_calls["delete"] == [unit_id]
    assert ais_stub.get(f"/api/knowledge/units/{unit_id}",
                        headers=as_user("admin")).status_code == 404


def test_update_unit_content_triggers_reindex(ais_stub, users, as_user):
    resp = _upload(ais_stub, as_user("hr001"), [("r.md", "旧内容".encode())])
    results = wait_terminal(ais_stub, as_user("hr001"), [t["task_id"] for t in resp.json()["data"]["tasks"]])
    unit_id = results[0]["unit_id"]

    before = len(ais_stub.ais_calls["index"])
    upd = ais_stub.put(f"/api/knowledge/units/{unit_id}", headers=as_user("hr001"),
                       json={"content": "全新的制度正文，需要重新切片与索引。"})
    assert upd.status_code == 200
    assert upd.json()["data"]["reindexed"] is True
    assert len(ais_stub.ais_calls["index"]) == before + 1
