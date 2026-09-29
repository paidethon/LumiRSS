"""NEW-277 模型配置用途约束 — 约束 CRUD / 触发阻断 / 可选模型面。"""

from fastapi.testclient import TestClient

from lumirss.ai_conversation import ConversationService
from lumirss.ai_settings import AiSettingsStore
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
BODY = "用途约束测试的正文。" * 8


def test_new277_constraint_blocks_disallowed_purpose(monkeypatch):
    """profile 限定 translation → chat 触发 409；解除约束后恢复。

    强制点在 deps._provider_factory_for（provider 构建前）；测试替换
    ai_provider.build_provider 为替身，让真实工厂（含约束检查）执行。"""
    provider = FakeProvider(outputs=["允许时的回答。"])
    db = Database(f"{_tmp()}/lumi.sqlite")
    adapter = FakeAdapter({ITEM_ID: make_detail(text=BODY)})
    configure_ai(db)
    monkeypatch.setattr(
        "lumirss.ai_provider.build_provider", lambda *a, **kw: provider
    )
    with TestClient(app) as client:
        app.state.db = db
        app.state.freshrss_adapter = adapter
        # 建一个 profile 并把 chat 映射过去（约束检查发生在 provider 构建之前，
        # 因此 profile 无需真实可用 key）
        profile = client.post(
            "/api/v1/settings/ai/profiles",
            json={"label": "翻译专用", "baseUrl": "https://x.example/v1",
                  "model": "m-translate"},
        )
        assert profile.status_code == 201, profile.text
        profile_id = profile.json()["id"]
        mapped = client.put(
            "/api/v1/settings/ai/purposes", json={"chat": profile_id}
        )
        assert mapped.status_code == 200, mapped.text

        constrained = client.put(
            f"/api/v1/settings/ai/profiles/{profile_id}/purpose-constraints",
            json={"allowedPurposes": ["translation"]},
        )
        assert constrained.status_code == 200, constrained.text
        assert constrained.json()["allowedPurposes"] == ["translation"]

        blocked = client.post(
            f"/api/v1/entries/{REF}/conversation/messages",
            json={"question": "这篇文章说了什么？"},
        )
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["error"]["type"] == "ai_purpose_not_allowed"
        assert "translation" in blocked.json()["error"]["message"]
        assert provider.calls == 0  # 绝不静默换模型，也不发上游请求

        # 可选模型面：当前映射被阻断，选项里给出 eligible 情况
        options = client.get("/api/v1/ai/purpose-options?purpose=chat").json()
        assert options["blocked"] is True
        current = next(
            o for o in options["options"] if o["isCurrentMapping"]
        )
        assert current["eligible"] is False
        assert current["constrained"] is True

        # 解除约束 → 行为恢复
        removed = client.delete(
            f"/api/v1/settings/ai/profiles/{profile_id}/purpose-constraints"
        )
        assert removed.status_code == 204
        ok = client.post(
            f"/api/v1/entries/{REF}/conversation/messages",
            json={"question": "这篇文章说了什么？"},
        )
        assert ok.status_code == 200, ok.text
        assert provider.calls == 1


def test_new277_constraint_validation(monkeypatch):
    """default 档不可约束；空清单/未知用途 → 422；未约束档 404。"""
    db = Database(f"{_tmp()}/lumi.sqlite")
    with TestClient(app) as client:
        app.state.db = db
        default_block = client.put(
            "/api/v1/settings/ai/profiles/default/purpose-constraints",
            json={"allowedPurposes": ["summary"]},
        )
        assert default_block.status_code == 422
        profile = client.post(
            "/api/v1/settings/ai/profiles",
            json={"label": "P", "baseUrl": "https://x.example/v1", "model": "m"},
        ).json()
        empty = client.put(
            f"/api/v1/settings/ai/profiles/{profile['id']}/purpose-constraints",
            json={"allowedPurposes": []},
        )
        assert empty.status_code == 422
        unknown = client.put(
            f"/api/v1/settings/ai/profiles/{profile['id']}/purpose-constraints",
            json={"allowedPurposes": ["quiz"]},
        )
        assert unknown.status_code == 422
        assert (
            client.get(
                f"/api/v1/settings/ai/profiles/{profile['id']}/purpose-constraints"
            ).status_code
            == 404
        )
        bogus = client.get("/api/v1/ai/purpose-options?purpose=nope")
        assert bogus.status_code == 422


def test_new277_unconstrained_default_unchanged(monkeypatch):
    """无约束行 = 未约束：默认解析完全走现行为（无 409）。"""
    provider = FakeProvider(outputs=["默认兜底的回答。"])
    db = Database(f"{_tmp()}/lumi.sqlite")
    adapter = FakeAdapter({ITEM_ID: make_detail(text=BODY)})
    configure_ai(db)
    conversation = ConversationService(
        db=db, adapter=adapter, settings_store=AiSettingsStore(db),
        provider_factory=_factory(provider),
    )
    with TestClient(app) as client:
        app.state.db = db
        app.state.freshrss_adapter = adapter
        app.state.conversation_service = conversation
        ok = client.post(
            f"/api/v1/entries/{REF}/conversation/messages",
            json={"question": "问题"},
        )
        assert ok.status_code == 200
        assert provider.calls == 1


def test_new277_cross_user_constraints_isolated(ab_env):  # noqa: F811
    """约束是 per-user 的：A 的约束不影响 B 的 purpose-options。"""
    env = ab_env
    client = env["client"]
    profile = client.post(
        "/api/v1/settings/ai/profiles",
        json={"label": "A 的档", "baseUrl": "https://x.example/v1", "model": "m"},
        headers=env["a"],
    )
    assert profile.status_code == 201, profile.text
    profile_id = profile.json()["id"]
    constrained = client.put(
        f"/api/v1/settings/ai/profiles/{profile_id}/purpose-constraints",
        json={"allowedPurposes": ["summary"]},
        headers=env["a"],
    )
    assert constrained.status_code == 200
    # B 看不到这个 profile，也读不到它的约束
    assert all(
        o["profileId"] != profile_id
        for o in client.get(
            "/api/v1/ai/purpose-options?purpose=summary", headers=env["b"]
        ).json()["options"]
    )
    assert (
        client.get(
            f"/api/v1/settings/ai/profiles/{profile_id}/purpose-constraints",
            headers=env["b"],
        ).status_code
        == 404
    )


def _factory(provider):
    async def factory(base_url: str, model: str):
        return provider

    return factory


def _tmp() -> str:
    import tempfile

    return tempfile.mkdtemp()
