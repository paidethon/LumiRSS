"""FIX-150 — 非批处理 AI 路径的重试次数/幂等性/费用反馈（单摘要 + TTS）。

单摘要路径既有契约已由既有套件钉住（此处只引用不重复）：
- tests/test_ai_summary.py::test_generate_calls_provider_once_and_persists
  （恰一次 provider 调用）、::test_concurrent_generation_makes_exactly_one_
  provider_call（并发去重，账面一次）、::test_provider_failure_persists_
  failed_state_with_type / test_provider_200_business_error_body_persists_
  failed_not_summary（失败绝不伪装成成功摘要）、::test_retry_after_failure_
  calls_provider_again_and_recovers（重试恰多一次，不重复计费）；
- tests/test_f064_ai_quota.py::test_f064_failed_calls_count_and_
  unconfigured_passes（配额预占即计数、失败不回退——保守多计的明示口径）；
- ai_provider.complete：空/空白摘要 → AiInvalidResponse（绝不存空成功）。

本文件补 TTS（另一条非批处理计费路径）缺失的同等契约：
1. 并发同键（text_hash+voice+model）去重 → 恰一次 provider 调用（同
   摘要路径的 lock-pool 幂等；修复前两次并发都 miss → 双重计费）；
2. provider 失败 → 恰一次调用（无内部重试放大）、无缓存行、诚实错误；
   用户重试 → 恰多一次真实调用（次数=账面）。
"""

import asyncio

import httpx
import pytest

from lumirss.storage import Database
from lumirss.tts_service import (
    TtsCacheStore,
    TtsProviderConfig,
    TtsUpstreamError,
    synthesize,
)

CONFIG = TtsProviderConfig(
    base_url="https://tts.example/v1", model="tts-1", api_key="sk-test"
)


class SlowCountingHttp(httpx.AsyncClient):
    """慢速计数替身：延迟返回让并发请求真实重叠。"""

    def __init__(self, audio: bytes = b"tts-audio", fail: bool = False):
        self.calls = 0
        self._audio = audio
        self._fail = fail

        def handler(request: httpx.Request) -> httpx.Response:
            self.calls += 1
            if self._fail:
                return httpx.Response(500, text="provider exploded")
            return httpx.Response(200, content=self._audio)

        super().__init__(transport=httpx.MockTransport(handler), trust_env=False)


@pytest.fixture()
def db(tmp_path):
    async def make():
        database = Database(str(tmp_path / "lumi.sqlite"))
        await database.migrate()
        return database

    return asyncio.run(make())


def test_tts_concurrent_duplicate_key_makes_exactly_one_provider_call(db):
    """并发同键合成 → 恰一次 provider 调用，双方拿到同一音频（幂等）。"""
    http = SlowCountingHttp()

    async def scenario():
        return await asyncio.gather(
            synthesize(db, http, CONFIG, text="同一句话", voice="alloy"),
            synthesize(db, http, CONFIG, text="同一句话", voice="alloy"),
        )

    (audio_a, hit_a), (audio_b, hit_b) = asyncio.run(scenario())
    assert audio_a == audio_b == b"tts-audio"
    assert http.calls == 1, f"并发同键产生 {http.calls} 次计费调用（应为 1）"
    assert sorted([hit_a, hit_b]) == [False, True]  # 恰一个 miss + 一个缓存命中


def test_tts_failure_is_bounded_one_call_then_retry_counts_one_more(db):
    """失败：恰一次调用（无内部重试）、零缓存行；重试恰多一次真实调用。"""
    http = SlowCountingHttp(fail=True)
    with pytest.raises(TtsUpstreamError):
        asyncio.run(synthesize(db, http, CONFIG, text="失败文本", voice="alloy"))
    assert http.calls == 1, "失败路径出现内部重试放大"
    assert asyncio.run(TtsCacheStore(db).list_entries())["count"] == 0

    # 用户显式重试 → 恰多一次真实调用（次数=账面，绝不静默重复）
    with pytest.raises(TtsUpstreamError):
        asyncio.run(synthesize(db, http, CONFIG, text="失败文本", voice="alloy"))
    assert http.calls == 2

    # provider 恢复后重试 → 一次成功并落缓存（诚实恢复）
    http._fail = False
    audio, hit = asyncio.run(
        synthesize(db, http, CONFIG, text="失败文本", voice="alloy")
    )
    assert audio == b"tts-audio" and hit is False
    assert http.calls == 3
    assert asyncio.run(TtsCacheStore(db).list_entries())["count"] == 1
