"""NEW-272 AI 草稿版本对照 — 生成/对照/保留/删除 + 不覆盖人工结论。

- 同一材料多方案草稿并列，diff 逐行对照，kept 组内单选；
- keep/delete 绝不写 ai_summaries / lumi_notes（负向断言锁定）。
"""

from contextlib import contextmanager

from fastapi.testclient import TestClient

from lumirss.ai_conversation import ConversationService
from lumirss.ai_settings import AiSettingsStore
from lumirss.main import app
from lumirss.storage import Database
from new2xx_ab import ab_env, seed_entry  # noqa: F401,F811 — pytest 夹具注册
from new271_helpers import (
    FakeAdapter,
    FakeProvider,
    configure_ai,
    entry_ref,
    item_id_of,
    make_detail,
)
from new271_helpers import (
    deps_factory as _deps_factory,
)

REF = entry_ref()
ITEM_ID = item_id_of(REF)
BODY = "草稿对照用的正文材料，内容保持稳定。" * 10


def _setup(monkeypatch, outputs: list[str] | None = None):
    provider = FakeProvider(outputs=outputs)
    db = Database(f"{_tmp()}/lumi.sqlite")
    adapter = FakeAdapter({ITEM_ID: make_detail(text=BODY)})
    configure_ai(db)
    conversation = ConversationService(
        db=db, adapter=adapter, settings_store=AiSettingsStore(db),
        provider_factory=_factory(provider),
    )
    monkeypatch.setattr(
        "lumirss.deps._provider_factory_for", _deps_factory(provider)
    )
    return db, adapter, provider, conversation


def _tmp() -> str:
    import tempfile

    return tempfile.mkdtemp()


def _factory(provider):
    async def factory(base_url: str, model: str):
        return provider

    return factory



@contextmanager
def _client(db, adapter, conversation):
    # 注入必须在 lifespan 之后（lifespan 会重置 app.state 注入位）。
    with TestClient(app) as client:
        app.state.db = db
        app.state.freshrss_adapter = adapter
        app.state.conversation_service = conversation
        yield client


def test_new272_generate_diff_keep_flow(monkeypatch):
    """生成两份方案草稿 → 对照 → 保留单选 → 删除；全部走 API。"""
    db, adapter, provider, conversation = _setup(
        monkeypatch, outputs=["方案甲的草稿。", "方案乙的草稿，略有不同。"]
    )
    with _client(db, adapter, conversation) as client:
        first = client.post(
            f"/api/v1/entries/{REF}/ai-drafts/generate",
            json={"schemeLabel": "要点式", "promptText": "请用要点总结本文"},
        )
        assert first.status_code == 201, first.text
        draft_a = first.json()
        assert draft_a["sourceKind"] == "generated"
        assert draft_a["promptText"] == "请用要点总结本文"

        second = client.post(
            f"/api/v1/entries/{REF}/ai-drafts/generate",
            json={"schemeLabel": "评论式", "promptText": "请写一段评论"},
        )
        assert second.status_code == 201, second.text
        draft_b = second.json()
        assert provider.calls == 2

        listing = client.get(f"/api/v1/entries/{REF}/ai-drafts").json()
        assert listing["total"] == 2
        assert listing["groups"][0]["materialHash"]  # 同组

        diff = client.get(
            f"/api/v1/ai-drafts/{draft_a['id']}/diff/{draft_b['id']}"
        )
        assert diff.status_code == 200, diff.text
        diff_body = diff.json()
        assert diff_body["identical"] is False
        assert "方案甲" in diff_body["unified"]

        # 手动保存第三份候选（零 provider）
        manual = client.post(
            f"/api/v1/entries/{REF}/ai-drafts",
            json={"schemeLabel": "手工版", "draftText": "我自己写的候选。"},
        )
        assert manual.status_code == 201, manual.text
        assert provider.calls == 2

        # 保留单选：先 A 后 B → 只有 B kept
        kept_a = client.post(f"/api/v1/ai-drafts/{draft_a['id']}/keep")
        assert kept_a.json()["kept"] is True
        kept_b = client.post(f"/api/v1/ai-drafts/{draft_b['id']}/keep").json()
        assert kept_b["kept"] is True
        still_a = client.get(f"/api/v1/ai-drafts/{draft_a['id']}").json()
        assert still_a["kept"] is False

        delete = client.delete(f"/api/v1/ai-drafts/{manual.json()['id']}")
        assert delete.status_code == 204
        assert (
            client.get(f"/api/v1/ai-drafts/{manual.json()['id']}").status_code
            == 404
        )


def test_new272_keep_never_touches_conclusion_surfaces(monkeypatch):
    """「不覆盖人工结论」：keep/保存草稿零写 ai_summaries / lumi_notes。"""
    import asyncio

    db, adapter, provider, conversation = _setup(monkeypatch, outputs=["草稿。"])
    with _client(db, adapter, conversation) as client:
        draft = client.post(
            f"/api/v1/entries/{REF}/ai-drafts/generate",
            json={"schemeLabel": "方案", "promptText": "写草稿"},
        ).json()
        client.post(f"/api/v1/ai-drafts/{draft['id']}/keep")
        client.post(
            f"/api/v1/entries/{REF}/ai-drafts",
            json={"schemeLabel": "手工", "draftText": "另一候选"},
        )

        async def counts():
            summaries = await db.fetch_one("SELECT COUNT(*) AS n FROM ai_summaries")
            notes = await db.fetch_one("SELECT COUNT(*) AS n FROM lumi_notes")
            return int(summaries["n"]), int(notes["n"])

        summary_count, note_count = asyncio.run(counts())
        assert summary_count == 0
        assert note_count == 0


def test_new272_validation_and_cross_group_diff(monkeypatch):
    """空方案名 422；不同材料的草稿对照 422；未知草稿 404。"""
    db, adapter, provider, conversation = _setup(monkeypatch, outputs=["x"])
    other_ref = entry_ref("tag:google.com,2005:reader/item/0000000000000002")
    adapter.entries[item_id_of(other_ref)] = make_detail(
        text="另一篇文章的正文。", ref="tag:google.com,2005:reader/item/0000000000000002"
    )
    with _client(db, adapter, conversation) as client:
        blank = client.post(
            f"/api/v1/entries/{REF}/ai-drafts/generate",
            json={"schemeLabel": " ", "promptText": "写"},
        )
        assert blank.status_code == 422

        draft_a = client.post(
            f"/api/v1/entries/{REF}/ai-drafts",
            json={"schemeLabel": "A", "draftText": "A 文"},
        ).json()
        draft_other = client.post(
            f"/api/v1/entries/{other_ref}/ai-drafts",
            json={"schemeLabel": "B", "draftText": "B 文"},
        ).json()
        cross = client.get(
            f"/api/v1/ai-drafts/{draft_a['id']}/diff/{draft_other['id']}"
        )
        assert cross.status_code == 422

        assert (
            client.get(
                f"/api/v1/ai-drafts/{draft_a['id']}/diff/no-such-draft"
            ).status_code
            == 404
        )


def test_new272_cross_user_drafts_isolated(ab_env, monkeypatch):  # noqa: F811
    """A 的草稿（含 kept 标记）对 B 完全不可见（per-user 库）。"""
    provider = FakeProvider()
    monkeypatch.setattr(
        "lumirss.deps._provider_factory_for", _deps_factory(provider)
    )
    env = ab_env
    if True:
        app.state.freshrss_adapter = FakeAdapter(
            {ITEM_ID: make_detail(text=BODY)}
        )
        draft = env["client"].post(
            f"/api/v1/entries/{REF}/ai-drafts",
            json={"schemeLabel": "A 的方案", "draftText": "A 的候选草稿"},
            headers=env["a"],
        )
        assert draft.status_code == 201, draft.text
        kept = env["client"].post(
            f"/api/v1/ai-drafts/{draft.json()['id']}/keep", headers=env["a"]
        )
        assert kept.status_code == 200

        assert (
            env["client"].get(
                f"/api/v1/ai-drafts/{draft.json()['id']}", headers=env["b"]
            ).status_code
            == 404
        )
        assert (
            env["client"]
            .get(f"/api/v1/entries/{REF}/ai-drafts", headers=env["b"])
            .json()["total"]
            == 0
        )
