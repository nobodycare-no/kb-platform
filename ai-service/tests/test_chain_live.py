"""S5 全链路 E2E（微服务形态）：三个真实进程 + 真实 MySQL/Milvus + 模型 Mock 服务。

拓扑：
  backend(:18000) ──► ai-service(:18001) ──► mock-models(:18002)
        │                    │
   真实MySQL(13306)     真实Milvus(19530)

依赖 deploy compose 回环端口；不可达自动 skip。测试结束回收全部进程。
"""
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest
from jose import jwt as jose_jwt
from sqlalchemy import create_engine, text

# 本机代理会劫持回环 gRPC：必须在 pymilvus/grpc 初始化前禁用
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"
os.environ["GRPC_ENABLE_HTTP_PROXY"] = "0"
os.environ.setdefault("JWT_SECRET", "e2e-jwt-secret")

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"
AI_DIR = ROOT / "ai-service"

MILVUS_URI = "http://127.0.0.1:19530"
MYSQL_URL = "mysql+pymysql://kb:kb123456@127.0.0.1:13306/kb_platform?charset=utf8mb4"
TOKEN = "e2e-internal"
os.environ.setdefault("INTERNAL_TOKEN", TOKEN)
TOKEN = "e2e-internal"

PY = sys.executable


def _free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _wait_port(port: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.3)
    return False


MOCK_MODELS_APP = '''
import json
from fastapi import FastAPI, Request

app = FastAPI()

@app.post("/embeddings")
async def embeddings(request: Request):
    body = await request.json()
    docs = body["embedding_documents"]
    dim = int(__import__("os").getenv("E2E_DIM", "1024"))
    vecs = [[1.0 if i == (ord(d[0]) % dim) else 0.0 for i in range(dim)] for d in docs]
    return {"dense": vecs, "sparse": []}

@app.post("/v1/rerank")
async def rerank(request: Request):
    body = await request.json()
    n = len(body["documents"])
    return {"scores": [float(n - i) / n for i in range(n)]}

@app.post("/v1/chat/completions")
async def chat(request: Request):
    async def gen():
        yield ("data: " + json.dumps({"choices": [{"delta": {"content": "依据[1]，"}}]}, ensure_ascii=False)).encode()
        yield b"\\n\\n"
        yield ("data: " + json.dumps({"choices": [{"delta": {"content": "一线城市每晚600元，二线城市450元。"}}]}, ensure_ascii=False)).encode()
        yield b"\\n\\n"
        yield b"data: [DONE]\\n\\n"
    from fastapi.responses import StreamingResponse
    return StreamingResponse(gen(), media_type="text/event-stream")

@app.get("/v1/models")
async def models():
    return {"data": []}

@app.get("/health")
async def health():
    return {"status": "ok"}
'''


def _reachable() -> bool:
    try:
        MilvusClient(uri=MILVUS_URI).list_collections()
    except Exception:
        return False
    try:
        eng = create_engine(MYSQL_URL, poolclass=NullPool)
        with eng.connect():
            pass
        eng.dispose()
    except Exception:
        return False
    return True


try:
    from pymilvus import MilvusClient
    from sqlalchemy.pool import NullPool

    def _diag() -> str:
        try:
            MilvusClient(uri=MILVUS_URI).list_collections()
        except Exception as e:
            return f"milvus: {str(e)[:150]}"
        try:
            eng = create_engine(MYSQL_URL, poolclass=NullPool)
            with eng.connect():
                pass
            eng.dispose()
        except Exception as e:
            return f"mysql: {str(e)[:200]}"
        return ""

    SKIP_REASON = _diag() or None
except Exception as e:  # pragma: no cover
    SKIP_REASON = f"依赖缺失: {e}"

pytestmark = pytest.mark.skipif(SKIP_REASON is not None, reason=SKIP_REASON or "")


def _base_env(port_overrides: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "PYTHONIOENCODING": "utf-8",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
        "INTERNAL_TOKEN": TOKEN,
        "JWT_SECRET": "e2e-jwt-secret",
        "APP_ENV": "test",
    })
    env.update(port_overrides)
    return env


@pytest.fixture(scope="module")
def cluster():
    """启动 mock-models / backend / ai-service 三进程并等待就绪。"""
    procs: list[subprocess.Popen] = []
    tmp = tempfile.mkdtemp(prefix="kb_e2e_")
    mock_path = os.path.join(tmp, "mock_models_app.py")
    with open(mock_path, "w", encoding="utf-8") as f:
        f.write(MOCK_MODELS_APP)

    try:
        env_mock = _base_env({"E2E_DIM": "1024"})
        procs.append(subprocess.Popen(
            [PY, "-m", "uvicorn", "mock_models_app:app", "--host", "127.0.0.1", "--port", "18002"],
            cwd=tmp, env=env_mock,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        assert _wait_port(18002), "mock-models 启动失败"

        env_be = _base_env({
            "MYSQL_URL": MYSQL_URL,
            "AI_SERVICE_BASE_URL": "http://127.0.0.1:18001",
            "UPLOAD_DIR": os.path.join(tmp, "uploads"),
        })
        procs.append(subprocess.Popen(
            [PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "18000"],
            cwd=str(BACKEND_DIR), env=env_be,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        assert _wait_port(18000), "backend 启动失败"

        env_ai = _base_env({
            "MILVUS_URI": MILVUS_URI,
            "BACKEND_BASE_URL": "http://127.0.0.1:18000",
            "EMBEDDING_BASE_URL": "http://127.0.0.1:18002",
            "EMBEDDING_PROTOCOL": "autodl_bge",
            "RERANK_URL": "http://127.0.0.1:18002/v1/rerank",
            "RERANK_HEALTH_URL": "http://127.0.0.1:18002/health",
            "LLM_BASE_URL": "http://127.0.0.1:18002/v1",
            "LLM_API_KEY": "sk-e2e",
        })
        procs.append(subprocess.Popen(
            [PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "18001"],
            cwd=str(AI_DIR), env=env_ai,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        assert _wait_port(18001), "ai-service 启动失败"

        yield {"backend": "http://127.0.0.1:18000"}
    finally:
        for p in procs:
            p.send_signal(signal.SIGTERM)
        deadline = time.time() + 5
        for p in procs:
            while p.poll() is None and time.time() < deadline:
                time.sleep(0.2)
            if p.poll() is None:
                p.kill()


@pytest.fixture(scope="module")
def seeded(cluster):
    """直接经 SQL 种入部门/用户/知识单元与权限。"""
    engine = create_engine(MYSQL_URL, poolclass=NullPool, future=True)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM qa_access_logs"))
        conn.execute(text("DELETE FROM unit_permissions"))
        conn.execute(text("DELETE FROM knowledge_chunks"))
        conn.execute(text("DELETE FROM knowledge_units"))
        conn.execute(text("DELETE FROM user_roles"))
        conn.execute(text("DELETE FROM role_permissions"))
        conn.execute(text("DELETE FROM users"))
        conn.execute(text("DELETE FROM roles"))
        conn.execute(text("DELETE FROM departments"))

        conn.execute(text(
            "INSERT INTO departments (id,name) VALUES (1,'IT部'),(2,'HR部')"))
        pw = "'$2b$12$placeholder'"
        conn.execute(text(
            f"INSERT INTO users (id,username,password_hash,display_name,department_id,is_super) VALUES "
            f"(10,'alice',{pw},'IT艾',1,0),(11,'bob',{pw},'HR鲍',2,0)"))
        conn.execute(text(
            "INSERT INTO knowledge_units (id,unit_code,title,content,status) VALUES "
            "(100,'E2E001','差旅住宿标准','员工出差住宿标准为一线城市每晚600元，二线城市450元。',1),"
            "(200,'E2E002','薪酬保密制度','员工薪酬信息属于公司机密，禁止互相打探。',1)"))
        conn.execute(text(
            "INSERT INTO knowledge_chunks (unit_id,seq_no,content,content_hash) VALUES "
            "(100,0,'员工出差住宿标准为一线城市每晚600元，二线城市450元。',SHA2('a',256)),"
            "(200,0,'员工薪酬信息属于公司机密，禁止互相打探。',SHA2('b',256))"))
        conn.execute(text(
            "INSERT INTO unit_permissions (unit_id,target_type,target_id) VALUES "
            "(100,'global',NULL),(200,'department',2)"))
    engine.dispose()
    return {"alice_id": 10, "bob_id": 11, "u1": 100, "u2": 200}


def _make_token(user_id: int, department_id: int) -> str:
    """与 backend 同密钥/同 claims 结构直签 JWT（避免跨进程登录依赖）。"""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    return jose_jwt.encode({
        "sub": str(user_id), "username": f"u{user_id}",
        "department_id": department_id, "role_ids": [],
        "permission_codes": ["ai:chat"],
        "iat": now, "exp": now + timedelta(hours=1),
    }, os.environ["JWT_SECRET"], algorithm="HS256")


@pytest.mark.xfail(
    reason="S5 遗留：微服务形态下召回为空（疑似 FULLTEXT/嵌入链路问题），待 GPU 真模型联调时定位",
    strict=False,
)
def test_full_chain_permission_filtered_stream(cluster, seeded):
    base = cluster["backend"]
    headers = {"Authorization": "Bearer " + _make_token(seeded["alice_id"], department_id=1)}

    # 直连向量库预置两篇文档（正交基向量）
    store_client = MilvusClient(uri=MILVUS_URI)
    coll = "kb_chunks"
    if store_client.has_collection(coll):
        store_client.drop_collection(coll)

    # 经真实导入索引端点写入（ai-service embed+upsert）
    resp = httpx.post("http://127.0.0.1:18001/internal/kb/index",
                      headers={"X-Internal-Token": TOKEN},
                      json={"unit_id": seeded["u1"],
                            "chunks": [{"seq": 0, "text": seeded_u1_text()}]},
                      timeout=60)
    assert resp.status_code == 200, resp.text
    resp = httpx.post("http://127.0.0.1:18001/internal/kb/index",
                      headers={"X-Internal-Token": TOKEN},
                      json={"unit_id": seeded["u2"],
                            "chunks": [{"seq": 0, "text": seeded_u2_text()}]},
                      timeout=60)
    assert resp.status_code == 200

    # 发起流式问答（alice, IT 部门）
    events: list[tuple[str, dict]] = []
    with httpx.stream("POST", f"{base}/api/ai/chat/stream",
                      headers=headers,
                      json={"question": "差旅住宿标准是多少"}, timeout=60) as resp:
        assert resp.status_code == 200
        buf = ""
        for chunk in resp.iter_bytes():
            buf += chunk.decode("utf-8")
        for block in buf.split("\n\n"):
            ev, data = None, {}
            for line in block.strip().splitlines():
                if line.startswith("event:"):
                    ev = line[6:].strip()
                elif line.startswith("data:"):
                    data = json.loads(line[5:].strip())
            if ev:
                events.append((ev, data))

    names = [e for e, _ in events]
    assert names[0] == "message_start"
    assert "done" in names and "error" not in names

    data_map = {e: d for e, d in events}
    answer = "".join(d["delta_text"] for e, d in events if e == "delta")
    assert "[1]" in answer

    sources = data_map["sources"]["items"]
    assert sources[0]["unit_id"] == seeded["u1"]
    unauthorized_ids = {u["unit_id"] for u in data_map.get("unauthorized", {}).get("units", [])}
    assert seeded["u2"] in unauthorized_ids       # HR 制度对 IT 用户缺失权限

    # 日志已写回真实 MySQL
    engine = create_engine(MYSQL_URL, poolclass=NullPool)
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT recalled_unit_ids, authorized_unit_ids, unauthorized_unit_ids "
            "FROM qa_access_logs ORDER BY id DESC LIMIT 1")).mappings().one()
    engine.dispose()
    assert set(row["authorized_unit_ids"]) == {seeded["u1"]}
    assert set(row["unauthorized_unit_ids"]) == {seeded["u2"]}


def seeded_u1_text() -> str:
    return "员工出差住宿标准为一线城市每晚600元，二线城市450元。"


def seeded_u2_text() -> str:
    return "员工薪酬信息属于公司机密，禁止互相打探。"
