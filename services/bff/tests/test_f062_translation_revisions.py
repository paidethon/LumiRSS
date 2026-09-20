"""F062 译文手工纠错与保护 — 修订保存/撤销、重生成保留、覆盖模式、
源文变化 stale 标记、API 行为。Provider 全部 fake，绝不真实调用。
"""

import asyncio

import pytest

from lumirss.ai_settings import AiSettingsUpdate
from lumirss.ai_translation_revisions import (
    SegmentRevisionNotFound,
    clear_revision,
    save_revision,
)
from lumirss.ai_translation_segments import (
    SegmentInput,
    SegmentTranslationService,
    block_hash,
    normalize_block_text,
)
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database


@pytest.fixture(autouse=True)
def _allow_fixture_endpoints(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "LUMIRSS_FETCH_ALLOW_PRIVATE_HOSTS", "127.0.0.1,ai.local"
    )


def run(coroutine):
    return asyncio.run(coroutine)


def _marker(index: int) -> str:
    return f"<<<BLOCK {index}>>>"


BLOCKS = [
    SegmentInput(index=0, text="First paragraph body."),
    SegmentInput(index=1, text="Second paragraph body."),
]


def _make_service(tmp_path, provider_factory):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    from lumirss.ai_settings import AiSettingsStore

    settings = AiSettingsStore(db)
    run(settings.save(AiSettingsUpdate(baseUrl="http://127.0.0.1:9999/v1", model="m1")))
    service = SegmentTranslationService(
        db=db,
        settings_store=settings,
        provider_factory=provider_factory,
        secrets=SecretsStore(tmp_path / "secrets.json"),
    )
    return service, db


def _echo_provider(calls, prompts):
    """fake provider：记录 prompt；按块回显「译<index>」。"""

    async def factory(base_url, model):
        calls["n"] += 1

        class FakeProvider:
            async def complete(self, messages):
                prompts.append(messages)
                import re

                markers = re.findall(r"^<<<BLOCK (\d+)>>>", messages[-1]["content"], re.M)
                return "\n\n".join(
                    f"{_marker(int(i))}\n译{int(i)}。" for i in markers
                )

        return FakeProvider()

    return factory


def test_f062_save_undo_and_regenerate_preserves_revisions(tmp_path):
    """保存/撤销修订；重生成默认保留已修订段（provider 请求不含修订段，
    调用数不增）；显式覆盖才重新生成并清修订。"""
    calls = {"n": 0}
    prompts: list = []
    service, db = _make_service(tmp_path, _echo_provider(calls, prompts))

    first = run(service.generate("e.f062", BLOCKS))
    assert [s.status for s in first] == ["success", "success"]
    assert calls["n"] == 1

    # 保存修订（块 1）：API/服务层同一存储
    rev = run(save_revision(db, "e.f062", 1, "我改过的译文。"))
    assert rev.text == "我改过的译文。"
    assert rev.source_hash == block_hash(normalize_block_text(BLOCKS[1].text))

    lookup = run(service.lookup("e.f062", BLOCKS))
    assert lookup[1].user_revision == "我改过的译文。"
    assert lookup[1].revision_stale is False
    assert lookup[0].user_revision is None

    # 重生成：修订段保留（不进 provider 请求、不增调用）；未修订段已是
    # 缓存命中 → 整体零 provider 调用
    before = calls["n"]
    second = run(service.generate("e.f062", BLOCKS))
    assert calls["n"] == before
    assert second[1].user_revision == "我改过的译文。"

    # 失败段与修订段并存：只重发失败且未修订的段
    run(clear_revision(db, "e.f062", 1))
    run(save_revision(db, "e.f062", 0, "修订零"))

    # 制造块 1 失败：改源文（新 hash 无成功行），并保存块 0 修订
    changed = [BLOCKS[0], SegmentInput(index=1, text="Second paragraph v2.")]
    before = calls["n"]
    regenerated = run(service.generate("e.f062", changed))
    assert calls["n"] == before + 1  # 只有块 1 的新源段需要 provider
    assert regenerated[0].user_revision == "修订零"  # 修订段保留
    assert regenerated[1].status == "success"
    # provider 的 prompt 只含块 1（块 0 已修订，未包含）
    last_prompt = prompts[-1][-1]["content"]
    assert "<<<BLOCK 1>>>" in last_prompt
    assert "<<<BLOCK 0>>>" not in last_prompt

    # 修订段无成功行时的「保留 vs 覆盖」分叉：块 1 换新源文（v3，无
    # 成功行）并保存修订 → 默认重生成：保留（零调用，not_generated）；
    # 显式覆盖：撤销修订并重发（进 prompt，calls+1）。
    run(save_revision(db, "e.f062", 0, "修订零"))
    fresh = [BLOCKS[0], SegmentInput(index=1, text="Second paragraph v3.")]
    run(save_revision(db, "e.f062", 1, "块一的修订"))
    before = calls["n"]
    preserved = run(service.generate("e.f062", fresh))
    assert calls["n"] == before  # 修订段保留：零 provider 调用
    assert preserved[1].user_revision == "块一的修订"
    assert preserved[1].status == "not_generated"
    assert preserved[0].user_revision == "修订零"

    before = calls["n"]
    overwritten = run(service.generate("e.f062", fresh, overwrite_revisions=True))
    assert calls["n"] == before + 1  # 撤销修订后块 1 重发
    assert overwritten[1].user_revision is None
    assert overwritten[0].user_revision is None
    last_prompt = prompts[-1][-1]["content"]
    assert "<<<BLOCK 1>>>" in last_prompt

    # 撤销：修订消失
    run(save_revision(db, "e.f062", 0, "临时修订"))
    lookup = run(service.lookup("e.f062", fresh))
    assert lookup[0].user_revision == "临时修订"
    run(clear_revision(db, "e.f062", 0))
    lookup = run(service.lookup("e.f062", fresh))
    assert lookup[0].user_revision is None


def test_f062_source_change_marks_stale_without_deleting(tmp_path):
    """源段变化 → 修订保留、stale=True；既单不误删也不假新鲜。"""
    calls = {"n": 0}
    prompts: list = []
    service, db = _make_service(tmp_path, _echo_provider(calls, prompts))
    run(service.generate("e.stale", BLOCKS))
    run(save_revision(db, "e.stale", 0, "手工修订零"))

    # 源文未变：stale=False
    lookup = run(service.lookup("e.stale", BLOCKS))
    assert lookup[0].revision_stale is False

    # 源文变化（块 0 文本更新）：修订仍按 index 关联，stale=True
    changed = [SegmentInput(index=0, text="First paragraph EDITED."), BLOCKS[1]]
    run(service.generate("e.stale", changed))
    lookup_new = run(service.lookup("e.stale", changed))
    assert lookup_new[0].user_revision == "手工修订零"
    assert lookup_new[0].revision_stale is True
    # 旧源文查缓存（仍存在的旧行）→ stale=False
    lookup_old = run(service.lookup("e.stale", BLOCKS))
    assert lookup_old[0].user_revision == "手工修订零"
    assert lookup_old[0].revision_stale is False


def test_f062_revision_requires_existing_segment_row(tmp_path):
    service, db = _make_service(tmp_path, _echo_provider({"n": 0}, []))
    with pytest.raises(SegmentRevisionNotFound):
        run(save_revision(db, "e.none", 3, "无锚修订"))
    with pytest.raises(SegmentRevisionNotFound):
        run(clear_revision(db, "e.none", 3))


def test_f062_revision_api_roundtrip_and_guards(client):
    """API：PUT 保存修订（lookup 响应携带 userRevision/revisionStale）、
    DELETE 撤销、无缓存行 404、空文本 422、越界 index 422。"""
    import asyncio
    import hashlib

    from lumirss.entryref import encode_entry_ref
    from lumirss.main import app

    source = "Hello world."
    b_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    # 服务层以 URL 中的原始 entryRef 字符串为缓存键 → 直接用编码后的 ref
    ref = encode_entry_ref("e1.f062api")

    async def _seed():
        await app.state.db.migrate()
        await app.state.db.execute(
            """INSERT OR IGNORE INTO ai_translation_segments (
            entry_ref, block_index, block_hash, provider, model, prompt_version,
            target_language, status, translated_text, failure_type, created_at, updated_at)
            VALUES (?, ?, ?, 'ai', '', 'translation-segments-v1', 'zh-CN', 'success', ?, NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
            (ref, 2, b_hash, "机器译文。"),
        )

    asyncio.run(_seed())

    url = f"/api/v1/entries/{ref}/translation/segments"

    # lookup 返回该段机器译文，暂无修订
    body = {"blocks": [{"index": 2, "text": source}]}
    lookup = client.post(f"{url}/lookup", json=body)
    assert lookup.status_code == 200, lookup.text
    seg = lookup.json()["segments"][0]
    assert seg["translatedText"] == "机器译文。"
    assert seg["userRevision"] is None
    assert seg["revisionStale"] is False

    # PUT 修订 → 响应携带修订；lookup 显示 userRevision
    put = client.put(f"{url}/2/revision", json={"text": "<script>alert(1)</script>我的修订"})
    assert put.status_code == 200, put.text
    assert put.json()["userRevision"].endswith("我的修订")
    lookup = client.post(f"{url}/lookup", json=body).json()
    assert lookup["segments"][0]["userRevision"].endswith("我的修订")
    assert lookup["segments"][0]["revisionStale"] is False

    # 源文变化（不同 hash）→ stale=True（修订保留）
    lookup_changed = client.post(
        f"{url}/lookup",
        json={"blocks": [{"index": 2, "text": "Hello EDITED world."}]},
    ).json()
    assert lookup_changed["segments"][0]["userRevision"] is not None
    assert lookup_changed["segments"][0]["revisionStale"] is True

    # DELETE 撤销 → 修订清空
    deleted = client.delete(f"{url}/2/revision")
    assert deleted.status_code == 204
    lookup = client.post(f"{url}/lookup", json=body).json()
    assert lookup["segments"][0]["userRevision"] is None

    # 守卫：空文本 422、超长 422、越界 index 422、无缓存行 404
    assert client.put(f"{url}/2/revision", json={"text": "   "}).status_code == 422
    assert (
        client.put(f"{url}/2/revision", json={"text": "x" * 10001}).status_code
        == 422
    )
    assert client.put(f"{url}/99/revision", json={"text": "x"}).status_code == 422
    assert (
        client.put(f"{url}/40/revision", json={"text": "x"}).status_code == 404
    )
