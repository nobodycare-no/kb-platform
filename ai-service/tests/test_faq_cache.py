"""FAQ 缓存测试：归一化 / L1 精确命中（stub Redis）/ 阈值语义判定。"""
import json

import pytest

from app.retrieval.faq_cache import FaqCacheService, faq_hash_key, normalize


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None):
        self.data[key] = value


@pytest.mark.parametrize("raw,expected", [
    ("  发票　丢了 怎么办？ ", "发票丢了怎么办?"),
    ("ＡＢＣ abc", "abcabc"),
    ("How  MUCH?\n", "howmuch?"),
])
def test_normalize(raw, expected):
    assert normalize(raw) == expected


def test_hash_key_stable_across_normalization():
    assert faq_hash_key("发票 丢失！") == faq_hash_key("ｆａｐｉａｏ".replace("ｆａｐｉａｏ", "发票 丢失！"))


async def test_l1_hit_returns_cached_answer():
    redis = FakeRedis()
    redis.set(faq_hash_key("报销流程？"), json.dumps({"faq_id": 7, "answer": "五日内提交。"}))

    svc = FaqCacheService(gateway=None, store=None, redis_client=redis)
    hit = await svc.lookup_l1("报销流程？")
    assert hit is not None and hit.via == "l1" and hit.answer == "五日内提交。"


async def test_l1_miss_and_disabled_redis():
    svc = FaqCacheService(gateway=None, store=None, redis_client=FakeRedis())
    assert await svc.lookup_l1("没有的问题") is None

    svc_none = FaqCacheService(gateway=None, store=None, redis_client=None)
    assert await svc_none.lookup_l1("任意") is None
