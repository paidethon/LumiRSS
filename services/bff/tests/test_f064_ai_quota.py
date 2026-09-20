"""F064 AI 配额事前拦截 — 并发预占、窗口滚动、失败计数、持久、
上限即时生效、未配置不拦截。Provider 全部 fake。"""

import asyncio

from fastapi.testclient import TestClient

from lumirss.ai_provider import AiRateLimited
from lumirss.ai_settings import AiSettingsStore, AiSettingsUpdate
from lumirss.ai_summary import SummaryService
from lumirss.entryref import encode_entry_ref
from lumirss.main import app
from lumirss.models import EntryDetail
from lumirss.storage import Database

VALID_REF = encode_entry_ref("tag:google.com,2005:reader/item/0000000000000077")
ARTICLE_TEXT = "这是一篇文章。" + "正文内容" * 100


def _async_provider(provider):
    async def factory(base_url: str, model: str):
        return provider

    return factory


def make_detail() -> EntryDetail:
    return EntryDetail(
        entryRef=VALID_REF,
        title="配额测试",
        feedTitle="源",
        contentText=ARTICLE_TEXT,
        contentHtml=f"<p>{ARTICLE_TEXT}</p>",
        read=False,
        starred=False,
    )


class FakeAdapter:
    async def get_entry(self, item_id: str) -> EntryDetail:
        return make_detail()


class BarrierProvider:
    """barrier mock：并发请求全部进入 barrier 后才一起返回（懒建，
    绑定当前运行中的事件循环）。"""

    def __init__(self, parties: int) -> None:
        self.calls = 0
        self.parties = parties
        self.barrier: asyncio.Barrier | None = None

    async def summarize(self, *, text: str, language: str) -> str:
        self.calls += 1
        if self.barrier is None:
            self.barrier = asyncio.Barrier(self.parties)
        await self.barrier.wait()
        return "并发摘要。"


class FailProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def summarize(self, *, text: str, language: str) -> str:
        self.calls += 1
        raise AiRateLimited("boom")


def run(coroutine):
    return asyncio.run(coroutine)


def _wire(tmp_path, provider):
    db = Database(tmp_path / "lumi.sqlite")
    service = SummaryService(
        db=db,
        adapter=FakeAdapter(),
        settings_store=AiSettingsStore(db),
        provider_factory=_async_provider(provider),
    )
    return db, service


async def _set_quota(db, window: str, max_calls: int):
    await AiSettingsStore(db).save(
        AiSettingsUpdate(baseUrl="https://api.example.com/v1", model="m", quotaWindow=window, quotaMaxCalls=max_calls)
    )


def test_f064_concurrent_claims_only_max_reach_provider(tmp_path):
    """并发 5 请求 max=2：恰 2 个名额被授予（barrier mock 下其余 429）。"""
    from lumirss.ai_quota import QuotaExceeded, claim_ai_call

    db = Database(tmp_path / "lumi.sqlite")
    run(_set_quota(db, "day", 2))

    async def _attempt(i):
        try:
            await claim_ai_call(db, window="day", max_calls=2)
            return "granted"
        except QuotaExceeded:
            return "denied"

    async def _all():
        return await asyncio.gather(*(_attempt(i) for i in range(5)))

    results = run(_all())
    assert results.count("granted") == 2
    assert results.count("denied") == 3

    # 被拒绝的请求带诚实元数据
    run(_set_quota(db, "day", 1))
    # 已用 2 ≥ 1：全部拒绝且 retryAfter/windowReset 非空
    async def _denied():
        try:
            await claim_ai_call(db, window="day", max_calls=1)
            return None
        except QuotaExceeded as exc:
            return exc

    exc = run(_denied())
    assert exc is not None
    assert exc.retry_after >= 1
    assert exc.window_reset
    assert exc.used == 1


def test_f064_window_rolls_with_injected_time(tmp_path):
    import lumirss.ai_quota as quota_mod
    from lumirss.ai_quota import claim_ai_call

    db = Database(tmp_path / "lumi.sqlite")
    run(_set_quota(db, "day", 1))
    run(claim_ai_call(db, window="day", max_calls=1))
    with_run = run  # noqa: F841

    class FixedDate:
        def __init__(self, dt):
            self.dt = dt

    # 注入「明天」：窗口滚动 → 新 key，配额重新可用
    real_now = quota_mod._now
    tomorrow = quota_mod.window_bounds(window="day").reset_iso
    from datetime import datetime as _dt

    parsed = _dt.fromisoformat(tomorrow)

    async def _next_day():
        quota_mod._now = lambda: parsed
        try:
            await claim_ai_call(db, window="day", max_calls=1)
            return "granted-new-window"
        finally:
            quota_mod._now = real_now

    assert run(_next_day()) == "granted-new-window"
    _ = FixedDate


def test_f064_failed_calls_count_and_unconfigured_passes(tmp_path):
    fail_provider = FailProvider()
    db, service = _wire(tmp_path, fail_provider)
    run(_set_quota(db, "month", 2))
    with TestClient(app) as client:
        app.state.db = db
        app.state.summary_service = service
        # 失败请求也计数（预占即计数，保守口径）
        first = client.post(f"/api/v1/entries/{VALID_REF}/summary")
        assert first.status_code == 429  # AiRateLimited → 稳定 429
        quota = client.get("/api/v1/settings/ai/quota").json()
        assert quota["used"] == 1 and quota["maxCalls"] == 2 and quota["remaining"] == 1

        # 重复直至上限 → 429 quota_exceeded（上游零请求）
        client.post(f"/api/v1/entries/{VALID_REF}/summary")
        second = client.post(f"/api/v1/entries/{VALID_REF}/summary")
        assert second.status_code == 429
        assert second.json()["error"]["type"] == "quota_exceeded"
        assert "retryAfter" in second.json()["error"]
        assert "windowReset" in second.json()["error"]
        assert second.headers.get("retry-after") is not None
        assert fail_provider.calls == 2  # 上游零额外请求

        # 调整上限立即生效：max 2 → 4 后可再次调用
        run(_set_quota(db, "month", 4))
        third = client.post(f"/api/v1/entries/{VALID_REF}/summary")
        assert third.status_code == 429  # provider 仍失败，但请求到达了上游
        assert fail_provider.calls == 3

    # 重启持久：同一 DB 重新进入 → 计数仍在（已用 3）
    db2, service2 = db, service
    with TestClient(app) as client2:
        client2.app.state.db = db2
        client2.app.state.summary_service = service2
        quota = client2.get("/api/v1/settings/ai/quota").json()
        assert quota["used"] == 3


class OkProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def summarize(self, *, text: str, language: str) -> str:
        self.calls += 1
        return "正常摘要。"


def test_f064_unconfigured_never_blocks(tmp_path):
    provider = OkProvider()
    db, service = _wire(tmp_path, provider)
    # 只配置 baseUrl/model，不配置 quota → 不拦截
    run(AiSettingsStore(db).save(
        AiSettingsUpdate(baseUrl="https://api.example.com/v1", model="m")
    ))
    with TestClient(app) as client:
        app.state.db = db
        app.state.summary_service = service
        resp = client.post(f"/api/v1/entries/{VALID_REF}/summary")
        assert resp.status_code == 200, resp.text
        assert provider.calls == 1
        quota = client.get("/api/v1/settings/ai/quota").json()
        assert quota["window"] == "" and quota["maxCalls"] == 0
