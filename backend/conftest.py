"""pytest 全局夹具。放在 backend/ 根目录使 `app` 包可导入。"""
import os

os.environ.setdefault("JWT_SECRET", "unit-test-secret")
os.environ.setdefault("APP_ENV", "test")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())
