"""NEW-276 AI 失败重放诊断 — 脱敏结构 / same·modified 路径 / 血缘。"""

from contextlib import contextmanager

from fastapi.testclient import TestClient

from lumirss.ai_conversation import ConversationService
from lumirss.ai_settings import AiSettingsStore
from lumirss.ai_summary import SummaryService
from lumirss.ai_task_log import AiTaskLogStore
from lumirss.main import app
from lumirss.storage import Database
from new2xx_ab import ab_env  # noqa: F401,F811 — pytest 夹具注册
from new271_helpers import (
    FakeAdapter,
    FakeProvider,
    configure_ai,
    entry_ref,
    item_id_of,
    make_detail,
)

REF = entry_ref()
ITEM_ID = item_id_of(REF)
BODY = "失败重放诊断用的正文。" * 10


def _setup(monkeypatch, outputs: list[str] | None = None):
    provider = FakeProvider(outputs=outputs)
    db = Database(f"{_tmp()}/lumi.sqlite")
    adapter = FakeAdapter({ITEM_ID: make_detail(text=BODY)})
    configure_ai(db)
    summary = SummaryService(
        db=db, adapter=adapter, settings_store=AiSettingsStore(db),
        provider_factory=_factory(provider),
    )
    conversation = ConversationService(
        db=db, adapter=adapter, settings_store=AiSettingsStore(db),
        provider_factory=_factory(provider),
    )
    return db, adapter, provider, summary, conversation


def _factory(provider):
    async def factory(base_url: str, model: str):
        return provider

    return factory


@contextmanager
def _client(db, adapter, summary, conversation):
    with TestClient(app) as client:
        app.state.db = db
        app.state.freshrss_adapter = adapter
        app.state.summary_service = summary
        app.state.conversation_service = conversation
        yield client


def _tmp() -> str:
    import tempfile

    return tempfile.mkdtemp()


def _seed_failed(db, kind: str, error: str = "timeout"):
    import asyncio

    async def seed():
        return await AiTaskLogStore(db).record(
            kind=kind, status="failed", entry_ref=REF, model="model-a",
            input_chars=1234, error_type=error,
        )

    return asyncio.run(seed())


def test_new276_diagnostic_redacted_and_same_replay(monkeypatch):
    """诊断只含结构字段；same 重放同配置重试并记录血缘。"""
    db, adapter, provider, summary, conversation = _setup(
        monkeypatch, outputs=["重放后的摘要。"]
    )
    failed_id = _seed_failed(db, "summary")
    with _client(db, adapter, summary, conversation) as client:
        diagnostic = client.get(f"/api/v1/ai/tasks/{failed_id}/replay-diagnostic")
        assert diagnostic.status_code == 200, diagnostic.text
        diag = diagnostic.json()
        assert diag["status"] == "failed"
        assert diag["errorType"] == "timeout"
        assert diag["inputChars"] == 1234
        assert diag["requestShape"]["entryRef"] == REF
        assert "从不入库" in diag["redactionNote"]
        assert BODY[:6] not in str(diag)  # 正文绝不出现在诊断里
        assert {m["mode"] for m in diag["replayModes"]} == {"same", "modified"}

        replay = client.post(
            f"/api/v1/ai/tasks/{failed_id}/replay",
            json={"mode": "same"},
        )
        assert replay.status_code == 201, replay.text
        assert replay.json()["mode"] == "same"
        assert provider.calls == 1  # 真的重放了

        lineage = client.get(f"/api/v1/ai/tasks/{failed_id}/replays").json()
        assert lineage["total"] == 1
        assert lineage["items"][0]["replayTaskId"] != failed_id


def test_new276_conversation_same_refused_modified_works(monkeypatch):
    """conversation 问题不入库 → same 诚实拒绝；modified 带新问题可行。"""
    db, adapter, provider, summary, conversation = _setup(
        monkeypatch, outputs=["新问题的回答。"]
    )
    failed_id = _seed_failed(db, "conversation", error="AiTimeout")
    with _client(db, adapter, summary, conversation) as client:
        refused = client.post(
            f"/api/v1/ai/tasks/{failed_id}/replay", json={"mode": "same"}
        )
        assert refused.status_code == 422
        assert refused.json()["error"]["type"] == "not_replayable_same"

        missing_question = client.post(
            f"/api/v1/ai/tasks/{failed_id}/replay",
            json={"mode": "modified"},
        )
        assert missing_question.status_code == 422
        assert missing_question.json()["error"]["type"] == "question_required"

        modified = client.post(
            f"/api/v1/ai/tasks/{failed_id}/replay",
            json={"mode": "modified", "question": "换个问法：结论是什么？"},
        )
        assert modified.status_code == 201, modified.text
        assert modified.json()["mode"] == "modified"
        assert provider.calls == 1


def test_new276_guards(monkeypatch):
    """成功任务 422 task_not_failed；未知任务 404；非法 mode 422。"""
    import asyncio

    db, adapter, provider, summary, conversation = _setup(monkeypatch)

    async def seed_success():
        return await AiTaskLogStore(db).record(kind="summary", status="done")

    success_id = asyncio.run(seed_success())
    with _client(db, adapter, summary, conversation) as client:
        assert (
            client.get(
                f"/api/v1/ai/tasks/{success_id}/replay-diagnostic"
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/api/v1/ai/tasks/no-such-task/replay-diagnostic"
            ).status_code
            == 404
        )
        failed_id = _seed_failed(db, "summary")
        bad_mode = client.post(
            f"/api/v1/ai/tasks/{failed_id}/replay", json={"mode": "rerun"}
        )
        assert bad_mode.status_code == 422
        assert bad_mode.json()["error"]["type"] == "invalid_mode"


def test_new276_cross_user_replays_isolated(ab_env):  # noqa: F811
    """A 的失败任务诊断对 B 是 404（不泄露他人任务存在性）。"""
    env = ab_env
    client = env["client"]
    import asyncio

    from lumirss.user_scope import user_context

    # 直接经 per-user 上下文向 A 的库写一条失败任务
    async def seed():
        with user_context(env["a"]["userId"]):
            await app.state.db.migrate()
            return await AiTaskLogStore(app.state.db).record(
                kind="summary", status="failed", entry_ref=REF,
                error_type="timeout",
            )

    failed_id = asyncio.run(seed())
    assert (
        client.get(
            f"/api/v1/ai/tasks/{failed_id}/replay-diagnostic", headers=env["a"]
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/v1/ai/tasks/{failed_id}/replay-diagnostic", headers=env["b"]
        ).status_code
        == 404
    )
