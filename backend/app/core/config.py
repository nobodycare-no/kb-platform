"""集中配置——全部来自环境变量（deploy/.env.example 为字段清单）。

pydantic-settings 默认大小写不敏感：环境变量 JWT_SECRET → jwt_secret。
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 基础
    app_env: str = "dev"
    jwt_secret: str = "dev-secret-change-me"
    jwt_expire_hours: int = 12
    internal_token: str = "dev-internal-token"

    # 存储
    mysql_url: str = "mysql+pymysql://kb:kb123456@localhost:3306/kb_platform?charset=utf8mb4"
    redis_url: str = "redis://localhost:6379/0"
    milvus_uri: str = "localhost:19530"

    # 模型接入（backend 不直连，仅供透传给 ai-service 的部署一致性检查）
    llm_base_url: str = ""
    embedding_base_url: str = ""
    rerank_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
