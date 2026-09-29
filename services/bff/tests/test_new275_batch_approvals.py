"""NEW-275 批量 AI 任务审批单 — 审批闸门 / 预算 / 取消未开始项。"""

from contextlib import contextmanager

from fastapi.testclient import TestClient

from lumirss.ai_conversation import ConversationService
from lumirss.ai_settings import AiSettingsStore
from lumirss.ai_summary import SummaryService
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

REFS = [
    entry_ref(f"tag:google.com,2005:reader/item/000000000000000{i}")
    for i in (1, 2, 3)
]


def _adapter():
    return FakeAdapter(
        {
            item_id_of(ref): make_detail(
                text=f"第 {i} 篇的正文，用于批量摘要。",
                ref=f"tag:google.com,2005:reader/item/000000000000000{i+1}",
            )
            for i, ref in enumerate(REFS)
        }
    )


def _setup(monkeypatch, outputs: list[str] | None = None, *, quota: int = 0):
    provider = FakeProvider(outputs=outputs)
    db = Database(f"{_tmp()}/lumi.sqlite")
    adapter = _adapter()
    configure_ai(db)
    summary = SummaryService(
        db=db, adapter=adapter, settings_store=AiSettingsStore(db),
        provider_factory=_factory(provider),
    )
    conversation = ConversationService(
        db=db, adapter=adapter, settings_store=AiSettingsStore(db),
        provider_factory=_factory(provider),
    )
    if quota:
        import asyncio


        asyncio.run(
            AiSettingsStore(db).save(
                type("Q", (), {"quotaWindow": "day", "quotaMaxCalls": quota})()
            )
        )
    return db, adapter, provider, summary, conversation


async def _save_quota(db, window: str, max_calls: int):
    from lumirss.ai_settings import AiSettingsStore, AiSettingsUpdate

    await AiSettingsStore(db).save(
        AiSettingsUpdate(quotaWindow=window, quotaMaxCalls=max_calls)
    )


def _factory(provider):
    async def factory(base_url: str, model: str):
        return provider

    return factory


@contextmanager
def _client(db, adapter, summary):
    with TestClient(app) as client:
        app.state.db = db
        app.state.freshrss_adapter = adapter
        app.state.summary_service = summary
        yield client


def _tmp() -> str:
    import tempfile

    return tempfile.mkdtemp()


def _create(client, budget: int = 3):
    response = client.post(
        "/api/v1/ai/batch-approvals",
        json={"kind": "summary", "entryRefs": REFS, "budgetCalls": budget},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_new275_approve_execute_complete(monkeypatch):
    """草稿 → 审批 → 执行全绿 → completed；逐项任务埋点。"""

    db, adapter, provider, summary, _conv = _setup(
        monkeypatch, outputs=["摘要一", "摘要二", "摘要三"]
    )
    with _client(db, adapter, summary) as client:
        approval = _create(client, budget=3)
        assert approval["status"] == "draft"

        early = client.post(f"/api/v1/ai/batch-approvals/{approval['id']}/execute")
        assert early.status_code == 409  # 未经确认不能执行

        approved = client.post(
            f"/api/v1/ai/batch-approvals/{approval['id']}/approve"
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"

        executed = client.post(
            f"/api/v1/ai/batch-approvals/{approval['id']}/execute"
        )
        assert executed.status_code == 200, executed.text
        body = executed.json()
        assert body["status"] == "completed"
        assert body["execution"]["done"] == 3
        assert body["execution"]["usedCalls"] == 3
        assert provider.calls == 3  # 预算内恰好三次调用
        assert all(i["status"] == "done" for i in body["items"])

        # 已完成后不能再次执行/取消
        assert (
            client.post(f"/api/v1/ai/batch-approvals/{approval['id']}/execute").status_code
            == 409
        )
        assert (
            client.post(f"/api/v1/ai/batch-approvals/{approval['id']}/cancel", json={}).status_code
            == 409
        )


def test_new275_budget_stops_honestly(monkeypatch):
    """预算 2 / 清单 3：两次调用后停止，剩余项保持 pending（绝不静默超额）。"""
    db, adapter, provider, summary, _conv = _setup(
        monkeypatch, outputs=["摘要一", "摘要二", "不会被调用"]
    )
    with _client(db, adapter, summary) as client:
        approval = _create(client, budget=2)
        client.post(f"/api/v1/ai/batch-approvals/{approval['id']}/approve")
        executed = client.post(
            f"/api/v1/ai/batch-approvals/{approval['id']}/execute"
        ).json()
        assert executed["execution"]["done"] == 2
        assert executed["execution"]["stoppedReason"] == "over_budget"
        assert executed["execution"]["remainingPending"] == 1
        assert provider.calls == 2
        assert executed["status"] == "approved"  # 未完成（还有 pending）
        pending_item = next(
            i for i in executed["items"] if i["status"] == "pending"
        )
        # 取消尚未开始的项
        cancelled = client.post(
            f"/api/v1/ai/batch-approvals/{approval['id']}/cancel",
            json={"itemId": pending_item["id"]},
        )
        assert cancelled.status_code == 200
        assert (
            next(
                i
                for i in cancelled.json()["items"]
                if i["id"] == pending_item["id"]
            )["status"]
            == "cancelled"
        )


def test_new275_quota_and_cancel_states(monkeypatch):
    """全局配额耗尽 → quota_exceeded 停止；已完成项不可取消。"""
    db, adapter, provider, summary, _conv = _setup(
        monkeypatch, outputs=["摘要一", "摘要二", "摘要三"]
    )
    import asyncio

    asyncio.run(_save_quota(db, "day", 1))
    with _client(db, adapter, summary) as client:
        approval = _create(client, budget=3)
        client.post(f"/api/v1/ai/batch-approvals/{approval['id']}/approve")
        executed = client.post(
            f"/api/v1/ai/batch-approvals/{approval['id']}/execute"
        ).json()
        assert executed["execution"]["done"] == 1
        assert executed["execution"]["stoppedReason"] == "quota_exceeded"
        done_item = next(i for i in executed["items"] if i["status"] == "done")
        # 已完成项不可取消（只有未开始项可取消）
        refused = client.post(
            f"/api/v1/ai/batch-approvals/{approval['id']}/cancel",
            json={"itemId": done_item["id"]},
        )
        assert refused.status_code == 409
        # 整单取消：剩余 pending 全部取消
        whole = client.post(
            f"/api/v1/ai/batch-approvals/{approval['id']}/cancel", json={}
        )
        assert whole.status_code == 200
        assert whole.json()["status"] == "cancelled"
        assert all(
            i["status"] in ("done", "failed", "quota_exceeded", "cancelled")
            for i in whole.json()["items"]
        )
        assert (
            client.post(
                f"/api/v1/ai/batch-approvals/{approval['id']}/execute"
            ).status_code
            == 409
        )


def test_new275_validation(monkeypatch):
    """kind 词表/空清单/重复条目/预算边界 → 422。"""
    db, adapter, provider, summary, _conv = _setup(monkeypatch)
    with _client(db, adapter, summary) as client:
        assert (
            client.post(
                "/api/v1/ai/batch-approvals",
                json={"kind": "quiz", "entryRefs": REFS, "budgetCalls": 2},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/ai/batch-approvals",
                json={"kind": "summary", "entryRefs": [], "budgetCalls": 2},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/ai/batch-approvals",
                json={
                    "kind": "summary",
                    "entryRefs": [REFS[0], REFS[0]],
                    "budgetCalls": 2,
                },
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/ai/batch-approvals",
                json={"kind": "summary", "entryRefs": REFS, "budgetCalls": 0},
            ).status_code
            == 422
        )
        assert (
            client.get("/api/v1/ai/batch-approvals/no-such").status_code == 404
        )


def test_new275_cross_user_approvals_isolated(ab_env):  # noqa: F811
    """A 的审批单对 B 不可见（清单本身也是个人数据）。"""
    env = ab_env
    client = env["client"]
    approval = client.post(
        "/api/v1/ai/batch-approvals",
        json={"kind": "summary", "entryRefs": REFS, "budgetCalls": 1},
        headers=env["a"],
    )
    assert approval.status_code == 201, approval.text
    assert (
        client.get("/api/v1/ai/batch-approvals", headers=env["b"]).json()["total"]
        == 0
    )
    assert (
        client.get(
            f"/api/v1/ai/batch-approvals/{approval.json()['id']}",
            headers=env["b"],
        ).status_code
        == 404
    )
    # B 不能取消/审批 A 的单
    assert (
        client.post(
            f"/api/v1/ai/batch-approvals/{approval.json()['id']}/cancel",
            json={},
            headers=env["b"],
        ).status_code
        == 404
    )
