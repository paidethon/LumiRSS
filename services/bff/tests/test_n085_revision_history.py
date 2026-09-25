"""N085 译文修订历史 — 历史栈（cap 5）、恢复上一版、API 行为。

Provider 全部 fake，绝不真实调用。
"""

import asyncio

import pytest

from lumirss.ai_translation_revisions import (
    REVISION_HISTORY_CAP,
    SegmentRevisionNotFound,
    clear_revision,
    restore_revision,
    revision_history,
    save_revision,
)
from lumirss.ai_translation_segments import SegmentInput
from lumirss.storage import Database


def run(coroutine):
    return asyncio.run(coroutine)


BLOCKS = [SegmentInput(index=0, text="First paragraph body.")]


def _make_db(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    return db


def _seed_segment(db, entry_ref="e.n085", index=0, text="机器译文。"):
    import hashlib

    b_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    run(
        db.execute(
            """INSERT OR IGNORE INTO ai_translation_segments (
            entry_ref, block_index, block_hash, provider, model, prompt_version,
            target_language, status, translated_text, failure_type, created_at, updated_at)
            VALUES (?, ?, ?, 'ai', 'm1', 'translation-segments-v1', 'zh-CN',
            'success', ?, NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
            (entry_ref, index, b_hash, text),
        )
    )


def test_n085_history_stack_and_cap(tmp_path):
    """覆盖修订时上一版进历史；每段上限 5 条，超出淘汰最旧。"""
    db = _make_db(tmp_path)
    _seed_segment(db)

    assert run(revision_history(db, "e.n085", 0)) == []

    # 首次修订：无历史（没有上一版可留）
    run(save_revision(db, "e.n085", 0, "修订 v1"))
    assert run(revision_history(db, "e.n085", 0)) == []

    # 覆盖 v1 → 历史出现 v1（最新在前）
    run(save_revision(db, "e.n085", 0, "修订 v2"))
    history = run(revision_history(db, "e.n085", 0))
    assert [h.old_text for h in history] == ["修订 v1"]

    # 连续覆盖到超过容量：历史保留最新 CAP 条，最旧淘汰
    for i in range(3, 10):
        run(save_revision(db, "e.n085", 0, f"修订 v{i}"))
    history = run(revision_history(db, "e.n085", 0))
    assert len(history) == REVISION_HISTORY_CAP
    assert [h.old_text for h in history] == [
        f"修订 v{i}" for i in range(8, 3, -1)
    ]
    # 当前修订 = 最新写入
    rows = run(
        db.fetch_all(
            "SELECT user_revision FROM ai_translation_segments WHERE entry_ref = ? AND block_index = 0",
            ("e.n085",),
        )
    )
    assert all(r["user_revision"] == "修订 v9" for r in rows)


def test_n085_restore_pops_latest_and_walks_back(tmp_path):
    """恢复上一版：弹出最新历史作为当前修订；逐次点击逐版回退；
    当前文本不回推历史；历史耗尽 → NotFound（当前修订保持不变）。"""
    db = _make_db(tmp_path)
    _seed_segment(db)

    run(save_revision(db, "e.n085", 0, "修订 v1"))
    run(save_revision(db, "e.n085", 0, "修订 v2"))
    run(save_revision(db, "e.n085", 0, "修订 v3"))

    restored = run(restore_revision(db, "e.n085", 0))
    assert restored.text == "修订 v2"
    assert [h.old_text for h in run(revision_history(db, "e.n085", 0))] == ["修订 v1"]

    restored = run(restore_revision(db, "e.n085", 0))
    assert restored.text == "修订 v1"
    assert run(revision_history(db, "e.n085", 0)) == []

    # 历史耗尽：404 语义（NotFound），当前修订仍是 v1
    with pytest.raises(SegmentRevisionNotFound):
        run(restore_revision(db, "e.n085", 0))
    rows = run(
        db.fetch_all(
            "SELECT user_revision FROM ai_translation_segments WHERE entry_ref = ? AND block_index = 0",
            ("e.n085",),
        )
    )
    assert all(r["user_revision"] == "修订 v1" for r in rows)


def test_n085_clear_does_not_push_history(tmp_path):
    """clear（撤销修订）按 F062 语义直接清空，不制造历史条目。"""
    db = _make_db(tmp_path)
    _seed_segment(db)
    run(save_revision(db, "e.n085", 0, "修订 v1"))
    run(save_revision(db, "e.n085", 0, "修订 v2"))
    run(clear_revision(db, "e.n085", 0))
    assert [h.old_text for h in run(revision_history(db, "e.n085", 0))] == ["修订 v1"]


def test_n085_history_requires_existing_segment_row(tmp_path):
    db = _make_db(tmp_path)
    with pytest.raises(SegmentRevisionNotFound):
        run(revision_history(db, "e.none", 3))
    with pytest.raises(SegmentRevisionNotFound):
        run(restore_revision(db, "e.none", 3))


def test_n085_history_api_roundtrip_and_guards(client):
    """API：GET history（最新在前）、POST restore、空历史 404、
    越界 index 422；restore 后 lookup 反映恢复出的修订。"""
    import asyncio
    import hashlib

    from lumirss.entryref import encode_entry_ref
    from lumirss.main import app

    source = "Hello world."
    b_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    ref = encode_entry_ref("e1.n085api")

    async def _seed():
        await app.state.db.migrate()
        await app.state.db.execute(
            """INSERT OR IGNORE INTO ai_translation_segments (
            entry_ref, block_index, block_hash, provider, model, prompt_version,
            target_language, status, translated_text, failure_type, created_at, updated_at)
            VALUES (?, ?, ?, 'ai', '', 'translation-segments-v1', 'zh-CN', 'success', ?, NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
            (ref, 1, b_hash, "机器译文。"),
        )

    asyncio.run(_seed())

    url = f"/api/v1/entries/{ref}/translation/segments"

    # 空历史 → 200 且 items=[]（UI 据此隐藏 恢复上一版）
    empty = client.get(f"{url}/1/revision/history")
    assert empty.status_code == 200, empty.text
    assert empty.json() == {"index": 1, "items": []}

    # 空历史 restore → 404 revision_history_empty
    restore = client.post(f"{url}/1/revision/restore")
    assert restore.status_code == 404, restore.text
    assert restore.json()["error"]["type"] == "revision_history_empty"

    # 保存 v1 → v2：历史含 v1；restore → 当前修订回到 v1
    put1 = client.put(f"{url}/1/revision", json={"text": "修订 v1"})
    assert put1.status_code == 200, put1.text
    client.put(f"{url}/1/revision", json={"text": "修订 v2"})

    history = client.get(f"{url}/1/revision/history").json()
    assert [item["oldText"] for item in history["items"]] == ["修订 v1"]

    restored = client.post(f"{url}/1/revision/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["userRevision"] == "修订 v1"
    assert restored.json()["revisionStale"] is False

    lookup = client.post(
        f"{url}/lookup", json={"blocks": [{"index": 1, "text": source}]}
    ).json()
    assert lookup["segments"][0]["userRevision"] == "修订 v1"

    # 历史已耗尽 → 再 restore 404
    assert client.post(f"{url}/1/revision/restore").status_code == 404

    # 越界 index：history 诚实返回空（无该段），restore 422
    assert client.get(f"{url}/99/revision/history").status_code == 200
    restore_bad = client.post(f"{url}/99/revision/restore")
    assert restore_bad.status_code == 422
    assert restore_bad.json()["error"]["type"] == "invalid_segment_index"
