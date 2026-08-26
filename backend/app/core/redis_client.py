"""共享同步 Redis 客户端（权限快照 / FAQ L1 缓存）。

不可用（未启动/网络失败）时返回 None，所有调用方必须优雅降级。
"""
from functools import lru_cache

import redis

from app.core.config import get_settings


@lru_cache
def get_redis():
    try:
        client = redis.Redis.from_url(
            get_settings().redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=2,
        )
        client.ping()
        return client
    except Exception:
        return None
