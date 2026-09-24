"""N086 不翻译片段标记 —— per-entry 块级「不翻译」持久标注。

- 标记块绝不产生 provider 请求（fake provider 计数 + prompt 内容断言）；
- 已有缓存译文的标记块照常展示（缓存译文原样返回）；
- 未翻译的标记块诚实保持 not_generated（显示原文）；
- unmark 恢复可翻译（provider 再次被调用）；
- 每条目 200 块上限（422）；
- API 层：PUT/DELETE 幂等 + lookup/generate 视图带 noTranslate 标志。
"""

import asyncio

import pytest

from lumirss.ai_settings import AiSettingsStore, AiSettingsUpdate
from lumirss.ai_translation_segments import (
    SegmentInput,
    SegmentTranslationService,
)
from lumirss.entry_no_translate import (
    MAX_NO_TRANSLATE_BLOCKS,
    NoTranslateCapExceeded,
    mark_block,
    marked_blocks,
    unmark_block,
)
from lumirss.entryref import encode_entry_ref
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database

run = asyncio.run

REF = encode_entry_ref("tag:google.com,2005:reader/item/0000000000000086")

BLOCKS = [
    SegmentInput(index=0, text="First paragraph body."),
    SegmentInput(index=1, text="Second paragraph body."),
    SegmentInput(index=2, text="Third paragraph body."),
]


@pytest.fixture(autouse=True)
def _allow_fixture_endpoints(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LUMIRSS_FETCH_ALLOW_PRIVATE_HOSTS", "127.0.0.1,ai.local")


def _make_service(tmp_path):
    calls = {"n": 0, "indexes": []}

    async def factory(base_url, model):
        class FakeProvider:
            async def complete(self, messages):
                calls["n"] += 1
                user_prompt = messages[1]["content"]
                import re

                indexes = [int(m) for m in re.findall(r"<<<BLOCK (\d+)>>>", user_prompt)]
                calls["indexes"].append(indexes)
                reply = "\n\n".join(
                    f"<<<BLOCK {index}>>>\n第{index}段译文。" for index in indexes
                )
                return reply

        return FakeProvider()

    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    settings = AiSettingsStore(db)
    service = SegmentTranslationService(
        db=db,
        settings_store=settings,
        provider_factory=factory,
        secrets=SecretsStore(tmp_path / "secrets.json"),
    )
    run(settings.save(
        AiSettingsUpdate(baseUrl="http://127.0.0.1:9999/v1", model="m1")
    ))
    return service, db, calls


# ---------------------------------------------------------------------------
# 存储层
# ---------------------------------------------------------------------------


def test_mark_unmark_idempotent(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    assert run(marked_blocks(db, "e1")) == set()
    run(mark_block(db, "e1", 3))
    run(mark_block(db, "e1", 3))  # 幂等
    assert run(marked_blocks(db, "e1")) == {3}
    run(unmark_block(db, "e1", 3))
    run(unmark_block(db, "e1", 3))  # 幂等
    assert run(marked_blocks(db, "e1")) == set()


def test_mark_cap_200_per_entry(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    for index in range(MAX_NO_TRANSLATE_BLOCKS):
        run(mark_block(db, "e1", index))
    assert run(marked_blocks(db, "e1")) == set(range(MAX_NO_TRANSLATE_BLOCKS))
    with pytest.raises(NoTranslateCapExceeded):
        run(mark_block(db, "e1", 200))
    # 已标记的块重复标记不超限（幂等 no-op）。
    run(mark_block(db, "e1", 5))
    # 其它条目不受影响。
    run(mark_block(db, "e2", 0))
    assert run(marked_blocks(db, "e2")) == {0}


# ---------------------------------------------------------------------------
# 生成链路：标记块零 provider 请求
# ---------------------------------------------------------------------------


def test_marked_block_never_sent_to_provider(tmp_path):
    service, db, calls = _make_service(tmp_path)
    run(mark_block(db, REF, 1))

    states = run(service.generate(REF, BLOCKS))

    assert [s.status for s in states] == ["success", "not_generated", "success"]
    assert states[1].no_translate is True
    assert states[1].translated_text is None  # 诚实：无缓存 → 显示原文
    assert states[0].no_translate is False
    # provider 只见过 0/2 两块（标记块绝不进入批次）。
    assert calls["n"] == 1
    assert all(1 not in indexes for indexes in calls["indexes"])
    assert sorted(calls["indexes"][0]) == [0, 2]


def test_marked_block_with_cached_translation_still_displayed(tmp_path):
    service, db, calls = _make_service(tmp_path)
    first = run(service.generate(REF, BLOCKS))
    assert first[1].translated_text == "第1段译文。"

    run(mark_block(db, REF, 1))
    second = run(service.generate(REF, BLOCKS))

    # 全部命中缓存/标记快照：provider 零调用；缓存译文原样展示。
    assert calls["n"] == 1
    assert second[1].status == "success"
    assert second[1].no_translate is True
    assert second[1].translated_text == "第1段译文。"
    assert second[1].cached is True


def test_unmark_restores_translatability(tmp_path):
    service, db, calls = _make_service(tmp_path)
    run(mark_block(db, REF, 1))
    marked = run(service.generate(REF, BLOCKS))
    assert marked[1].status == "not_generated"
    assert calls["n"] == 1

    run(unmark_block(db, REF, 1))
    states = run(service.lookup(REF, BLOCKS))
    assert states[1].status == "not_generated"
    assert states[1].no_translate is False

    regenerated = run(service.generate(REF, BLOCKS))
    assert regenerated[1].status == "success"
    assert regenerated[1].translated_text == "第1段译文。"
    assert calls["n"] == 2  # unmark 后 provider 再次被调用
    assert any(1 in indexes for indexes in calls["indexes"])


# ---------------------------------------------------------------------------
# API 层
# ---------------------------------------------------------------------------


def test_api_mark_unmark_and_view_flags(client):
    from lumirss.ai_translation_segments import (
        SegmentTranslationService as Svc,
    )
    from lumirss.main import app as _app

    db = _app.state.db
    # 注入真实段服务（共享 client 的临时 DB；lookup/mark 端点只读缓存）。
    _app.state.segment_translation_service = Svc(
        db=db,
        settings_store=AiSettingsStore(db),
        provider_factory=_never_factory,
        secrets=_app.state.secrets_store,
    )

    base = f"/api/v1/entries/{REF}/translation/segments"
    resp = client.put(f"{base}/2/no-translate")
    assert resp.status_code == 204, resp.text
    resp = client.put(f"{base}/2/no-translate")  # 幂等
    assert resp.status_code == 204

    body = client.post(
        f"{base}/lookup",
        json={"blocks": [{"index": 2, "text": "hello world"}]},
    ).json()
    assert body["segments"][0]["noTranslate"] is True
    assert body["segments"][0]["status"] == "not_generated"

    resp = client.delete(f"{base}/2/no-translate")
    assert resp.status_code == 204
    body = client.post(
        f"{base}/lookup",
        json={"blocks": [{"index": 2, "text": "hello world"}]},
    ).json()
    assert body["segments"][0]["noTranslate"] is False


def test_api_invalid_block_index_rejected(client):
    base = f"/api/v1/entries/{REF}/translation/segments"
    resp = client.put(f"{base}/64/no-translate")
    assert resp.status_code == 422
    assert resp.json()["error"]["type"] == "invalid_segment_index"
    resp = client.delete(f"{base}/-1/no-translate")
    assert resp.status_code == 422


async def _never_factory(base_url, model):
    raise AssertionError("provider must never be built in this flow")
