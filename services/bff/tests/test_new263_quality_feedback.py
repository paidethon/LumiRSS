"""NEW-263 译文质量反馈 — 段级漏译/误译/格式标记 + 本人待复核队列。

- 创建时刻快照 原文/机器译文/人工修订（关联原文，源文后续更新不动）；
- resolve / delete 显式出队；重复 resolve / 未知 id → 404；
- A/B 隔离：alice 的反馈队列对 bob 完全不可见（per-user 库）。
"""

import asyncio
import re

import pytest

from lumirss.ai_settings import AiSettingsStore, AiSettingsUpdate
from lumirss.ai_translation_segments import (
    SegmentInput,
    SegmentTranslationService,
)
from lumirss.entryref import encode_entry_ref
from lumirss.new263_quality_feedback import (
    FeedbackInvalid,
    FeedbackNotFound,
    create_feedback,
    delete_feedback,
    list_feedback,
    queue,
    resolve_feedback,
)
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database
from new2xx_ab import ab_env, seed_entry  # noqa: F401,F811

run = asyncio.run


@pytest.fixture(autouse=True)
def _allow_fixture_endpoints(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LUMIRSS_FETCH_ALLOW_PRIVATE_HOSTS", "127.0.0.1,ai.local")


def _echo_provider(calls):
    async def factory(base_url, model):
        calls["n"] += 1

        class FakeProvider:
            async def complete(self, messages):
                markers = re.findall(
                    r"^<<<BLOCK (\d+)>>>", messages[-1]["content"], re.M
                )
                return "\n\n".join(
                    f"<<<BLOCK {int(i)}>>>\n译{int(i)}。" for i in markers
                )

        return FakeProvider()

    return factory


def _make(tmp_path, calls):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    settings = AiSettingsStore(db)
    run(settings.save(AiSettingsUpdate(baseUrl="http://127.0.0.1:9/v1", model="m1")))
    service = SegmentTranslationService(
        db=db,
        settings_store=settings,
        provider_factory=_echo_provider(calls),
        secrets=SecretsStore(tmp_path / "secrets.json"),
    )
    return service, db


def _seed_feedback(tmp_path, entry_key: str, with_revision: bool = False):
    calls = {"n": 0}
    service, db = _make(tmp_path, calls)
    blocks = [
        SegmentInput(index=0, text="Source zero."),
        SegmentInput(index=1, text="Source one."),
    ]
    run(service.generate(encode_entry_ref(f"e1.{entry_key}"), blocks))
    if with_revision:
        from lumirss.ai_translation_revisions import save_revision

        run(save_revision(db, encode_entry_ref(f"e1.{entry_key}"), 1, "人工版"))
    return db, encode_entry_ref(f"e1.{entry_key}")


def test_create_snapshots_source_machine_and_revision(tmp_path):
    db, ref = _seed_feedback(tmp_path, "n263a", with_revision=True)
    item = run(create_feedback(db, ref, 1, "mistranslation", "语义翻反了"))
    assert item["issueKind"] == "mistranslation"
    assert item["sourceExcerpt"] == "Source one."
    assert item["machineExcerpt"] == "译1。"
    assert item["revisedExcerpt"] == "人工版"
    assert item["status"] == "open"

    # 无修订段：revised_excerpt 为 None
    plain = run(create_feedback(db, ref, 0, "omission", "漏了一整句"))
    assert plain["revisedExcerpt"] is None


def test_feedback_validation_and_unknown_segment(tmp_path):
    db, ref = _seed_feedback(tmp_path, "n263b")
    with pytest.raises(FeedbackInvalid):
        run(create_feedback(db, ref, 0, "style", "不在三种类型内"))
    with pytest.raises(FeedbackInvalid):
        run(create_feedback(db, ref, 9, "omission", "没有缓存行"))
    with pytest.raises(FeedbackInvalid):
        run(create_feedback(db, ref, 0, "omission", "x" * 501))


def test_queue_order_resolve_and_delete(tmp_path):
    db, ref = _seed_feedback(tmp_path, "n263c")
    first = run(create_feedback(db, ref, 0, "omission", "第一"))
    second = run(create_feedback(db, ref, 1, "format", "第二"))
    ids = [item["id"] for item in run(queue(db))]
    assert ids == [second["id"], first["id"]]  # 新→旧
    assert [item["id"] for item in run(list_feedback(db, ref))] == ids  # 某篇视图同序

    resolved = run(resolve_feedback(db, first["id"]))
    assert resolved["status"] == "resolved"
    assert resolved["resolvedAt"] is not None
    with pytest.raises(FeedbackNotFound):
        run(resolve_feedback(db, first["id"]))  # 重复 resolve → 404
    assert [item["id"] for item in run(queue(db))] == [second["id"]]

    assert run(delete_feedback(db, second["id"])) is True
    assert run(queue(db)) == []
    assert run(delete_feedback(db, second["id"])) is False  # 已删除 → False


# ---------------------------------------------------------------------------
# API 行为
# ---------------------------------------------------------------------------


def _seed_api(client, entry_key: str, calls: dict | None = None):
    async def run_seed():
        from lumirss.main import app as lumi_app

        db = lumi_app.state.db
        await db.migrate()
        settings = AiSettingsStore(db)
        await settings.save(
            AiSettingsUpdate(baseUrl="http://127.0.0.1:9/v1", model="m1")
        )
        service = SegmentTranslationService(
            db=db,
            settings_store=settings,
            provider_factory=_echo_provider(calls if calls is not None else {"n": 0}),
            secrets=SecretsStore(f"/tmp/n263-{entry_key}-secrets.json"),
        )
        blocks = [
            SegmentInput(index=0, text="Source zero."),
            SegmentInput(index=1, text="Source one."),
        ]
        await service.generate(encode_entry_ref(f"e1.{entry_key}"), blocks)
        lumi_app.state.segment_translation_service = service

    run(run_seed())
    return encode_entry_ref(f"e1.{entry_key}")


def test_api_feedback_roundtrip(client):
    ref = _seed_api(client, "n263api")

    made = client.post(
        f"/api/v1/entries/{ref}/translation/segments/0/feedback",
        json={"issueKind": "omission", "note": "漏译了一句"},
    )
    assert made.status_code == 200, made.text
    body = made.json()
    assert body["sourceExcerpt"] == "Source zero."

    invalid = client.post(
        f"/api/v1/entries/{ref}/translation/segments/0/feedback",
        json={"issueKind": "tone", "note": "未知类型"},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["type"] == "feedback_invalid"

    bad_index = client.post(
        f"/api/v1/entries/{ref}/translation/segments/99/feedback",
        json={"issueKind": "omission"},
    )
    assert bad_index.status_code == 422

    entry_items = client.get(f"/api/v1/entries/{ref}/translation/feedback").json()
    assert len(entry_items["feedback"]) == 1

    feedback_id = body["id"]
    queue = client.get("/api/v1/translation/feedback/queue").json()["queue"]
    assert [item["id"] for item in queue] == [feedback_id]

    resolved = client.post(f"/api/v1/translation/feedback/{feedback_id}/resolve")
    assert resolved.status_code == 200
    assert client.get("/api/v1/translation/feedback/queue").json()["queue"] == []

    unknown_resolve = client.post("/api/v1/translation/feedback/tqf-404/resolve")
    assert unknown_resolve.status_code == 404
    unknown_delete = client.delete("/api/v1/translation/feedback/tqf-404")
    assert unknown_delete.status_code == 404


# ---------------------------------------------------------------------------
# A/B 隔离
# ---------------------------------------------------------------------------


def test_ab_feedback_queue_isolated(ab_env):  # noqa: F811
    env = ab_env
    client = env["client"]

    def seed(who: str, key: str):
        from lumirss.main import app as lumi_app
        from lumirss.user_scope import user_context

        async def run_seed():
            with user_context(env[who]["userId"]):
                db = lumi_app.state.db
                await db.migrate()
                settings = AiSettingsStore(db)
                await settings.save(
                    AiSettingsUpdate(baseUrl="http://127.0.0.1:9/v1", model="m1")
                )
                service = SegmentTranslationService(
                    db=db,
                    settings_store=settings,
                    provider_factory=_echo_provider({"n": 0}),
                    secrets=lumi_app.state.secrets_store,
                )
                await service.generate(
                    encode_entry_ref("e1.new263ab"),
                    [SegmentInput(index=0, text=f"Text of {who}.")],
                )

        run(run_seed())
        seed_entry(env, who, key)

    seed("a", "new263ab")
    seed("b", "new263ab")
    ref = encode_entry_ref("e1.new263ab")

    made_a = client.post(
        f"/api/v1/entries/{ref}/translation/segments/0/feedback",
        json={"issueKind": "mistranslation", "note": "A 发现的问题"},
        headers=env["a"],
    )
    made_b = client.post(
        f"/api/v1/entries/{ref}/translation/segments/0/feedback",
        json={"issueKind": "format", "note": "B 发现的问题"},
        headers=env["b"],
    )
    assert made_a.status_code == 200 and made_b.status_code == 200

    a_queue = client.get("/api/v1/translation/feedback/queue", headers=env["a"])
    b_queue = client.get("/api/v1/translation/feedback/queue", headers=env["b"])
    assert [item["note"] for item in a_queue.json()["queue"]] == ["A 发现的问题"]
    assert [item["note"] for item in b_queue.json()["queue"]] == ["B 发现的问题"]

    # A 不能 resolve B 的反馈（未知 id → 404）
    cross = client.post(
        f"/api/v1/translation/feedback/{made_b.json()['id']}/resolve",
        headers=env["a"],
    )
    assert cross.status_code == 404
