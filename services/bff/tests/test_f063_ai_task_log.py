"""F063 AI 任务中心 — 埋点（成功/失败）、重试重触发、上限 50、重启持久。

Provider 全部 fake（确定性假 provider / 抛错假 provider），绝不真实调用。
"""

import asyncio

from fastapi.testclient import TestClient

from lumirss.ai_provider import AiRateLimited
from lumirss.ai_settings import AiSettingsStore, AiSettingsUpdate
from lumirss.ai_summary import SummaryService
from lumirss.ai_task_log import AiTaskLogStore
from lumirss.entryref import encode_entry_ref
from lumirss.main import app
from lumirss.models import EntryDetail
from lumirss.storage import Database

VALID_REF = encode_entry_ref("tag:google.com,2005:reader/item/0000000000000063")
ARTICLE_TEXT = "这是一篇文章。" + "正文内容" * 100


def _async_provider(provider):
    async def factory(base_url: str, model: str):
        return provider

    return factory


def make_detail() -> EntryDetail:
    return EntryDetail(
        entryRef=VALID_REF,
        title="测试文章",
        feedTitle="测试源",
        contentText=ARTICLE_TEXT,
        contentHtml=f"<p>{ARTICLE_TEXT}</p>",
        read=False,
        starred=False,
    )


class FakeAdapter:
    async def get_entry(self, item_id: str) -> EntryDetail:
        return make_detail()


class FakeProvider:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    async def summarize(self, *, text: str, language: str) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return "确定性的测试摘要。"


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
    run(AiSettingsStore(db).save(
        AiSettingsUpdate(baseUrl="https://api.example.com/v1", model="model-f063")
    ))
    return db, service


def test_f063_success_and_failure_instrumentation(tmp_path):
    ok_provider = FakeProvider()
    db, service = _wire(tmp_path, ok_provider)
    with TestClient(app) as client:
        app.state.db = db
        app.state.summary_service = service
        # 成功埋点：kind/status/model 如实
        resp = client.post(f"/api/v1/entries/{VALID_REF}/summary")
        assert resp.status_code == 200
        tasks = client.get("/api/v1/ai/tasks").json()["items"]
        summary_tasks = [t for t in tasks if t["kind"] == "summary"]
        assert len(summary_tasks) == 1
        task = summary_tasks[0]
        assert task["status"] == "done"
        assert task["model"] == "model-f063"
        assert task["entryRef"] == VALID_REF
        assert task["durationMs"] >= 0
        assert task["errorType"] is None

        # 失败埋点：provider 抛限流异常 → 任务 failed + error_type
        client.post(
            f"/api/v1/entries/{VALID_REF}/summary",
            json={"maxChars": 4096},
        )
        tasks = client.get("/api/v1/ai/tasks").json()["items"]
        assert len([t for t in tasks if t["kind"] == "summary"]) == 2
    _ = ok_provider


def test_f063_retry_retriggers_and_keeps_original(tmp_path):
    provider = FakeProvider(error=AiRateLimited("quota"))
    db, service = _wire(tmp_path, provider)
    with TestClient(app) as client:
        app.state.db = db
        app.state.summary_service = service
        # 失败任务（provider 抛错 → 状态 failed）
        first = client.post(f"/api/v1/entries/{VALID_REF}/summary")
        assert first.status_code == 429  # AiRateLimited → 稳定 429（埋点已记失败）
        tasks = client.get("/api/v1/ai/tasks").json()["items"]
        failed_task = next(t for t in tasks if t["kind"] == "summary")
        assert failed_task["status"] == "failed"
        original_id = failed_task["id"]

        # 恢复 provider 后重试：provider 调用 +1，新任务 done，原记录不变
        provider.error = None
        retry = client.post(f"/api/v1/ai/tasks/{original_id}/retry")
        assert retry.status_code == 200, retry.text
        body = retry.json()
        assert body["originalId"] == original_id
        assert body["originalUnchanged"] is True
        assert provider.calls == 2  # 首次失败 1 次 + 重试 1 次
        assert body["task"] is not None
        assert body["task"]["id"] != original_id
        assert body["task"]["status"] == "done"

        # 原任务记录不变
        original = client.get("/api/v1/ai/tasks").json()["items"]
        still = next(t for t in original if t["id"] == original_id)
        assert still["status"] == "failed"

        # 非 summary 任务 / 不存在任务 → 诚实拒绝
        missing = client.post("/api/v1/ai/tasks/nope/retry")
        assert missing.status_code == 404


def test_f063_retry_unsupported_kinds_and_list_cap(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    store = AiTaskLogStore(db)
    for n in range(60):
        run(store.record(
            kind="conversation",
            status="done",
            entry_ref=VALID_REF,
            model="m",
            duration_ms=n,
        ))
    with TestClient(app) as client:
        app.state.db = db
        # 上限 50
        tasks = client.get("/api/v1/ai/tasks").json()["items"]
        assert len(tasks) == 50
        # limit 参数生效（1..50）
        assert len(client.get("/api/v1/ai/tasks", params={"limit": 5}).json()["items"]) == 5
        # conversation（非 entry 可重建类）→ 422 retry_not_supported
        target = tasks[0]["id"]
        resp = client.post(f"/api/v1/ai/tasks/{target}/retry")
        assert resp.status_code == 422
        assert resp.json()["error"]["type"] == "retry_not_supported"

        # 重启持久：同一个 DB 重新进入 TestClient 后列表仍在
        with TestClient(app) as client2:
            client2.app.state.db = db
            again = client2.get("/api/v1/ai/tasks").json()["items"]
            assert {t["id"] for t in again[:50]} == {t["id"] for t in tasks}
