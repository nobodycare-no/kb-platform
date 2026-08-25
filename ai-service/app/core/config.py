"""AI 网关配置：模型三件套地址/协议/密钥全部来自环境变量。

AutoDL 双端口约束：6006=vLLM(LLM)；6008=bge-m3 与 reranker 同进程双接口。
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 服务间信任
    internal_token: str = "dev-internal-token"
    backend_base_url: str = "http://backend:8000"

    # --- LLM（OpenAI 兼容，vLLM）---
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "qwen3-8b"
    llm_max_context: int = 8192
    llm_fail_switch: int = 2          # 连续失败 N 次后粘性切换 fallback
    llm_fallback_base_url: str = ""
    llm_fallback_api_key: str = ""
    llm_fallback_model: str = ""
    llm_timeout_s: int = 120

    # --- Embedding ---
    embedding_base_url: str = ""
    embedding_protocol: str = "autodl_bge"   # autodl_bge | openai
    embedding_api_key: str = ""
    embedding_model: str = "bge-m3"
    embed_dim: int = 1024
    embed_timeout_s: int = 60

    # --- Reranker ---
    rerank_url: str = ""                       # custom: .../v1/rerank；tei: 完整端点
    rerank_health_url: str = ""
    rerank_protocol: str = "custom"            # custom | tei
    rerank_timeout_s: int = 60

    # --- Milvus ---
    milvus_uri: str = "milvus-standalone:19530"

    # --- 检索参数（SDD §7）---
    dense_top_k: int = 50
    keyword_top_k: int = 20
    keyword_timeout_ms: int = 200
    rrf_k: int = 60
    rerank_top_n: int = 6
    faq_exact_sim: float = 0.92


@lru_cache
def get_settings() -> Settings:
    return Settings()
