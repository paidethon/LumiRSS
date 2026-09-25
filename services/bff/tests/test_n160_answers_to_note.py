"""N160 从答案生成证据笔记测试。

- POST /api/v1/rag/answers-to-note：assistant 消息（带引用）→ 三段式
  证据笔记（摘录 = 精确原文 span + ref；生成内容显式标注 AI 生成；
  人工修改段初始为空）；
- 会话外/非 assistant 消息 id → 422 citation_invalid；未知会话 → 404；
- 后续编辑把上一版推入 lumi_note_revisions（provenance 保留）；
  普通手写笔记编辑不入台账。
"""

import asyncio

from lumirss.agent_store import AgentStore
from lumirss.search_library import LibrarySearchWriter

_REF = "library:3a8df3e0-1f2a-4c3d-9e4f-5a6b7c8d9e0f"


def run(coroutine):
    return asyncio.run(coroutine)


async def _seed_clip(db) -> None:
    await LibrarySearchWriter(db).upsert(
        ref=_REF,
        kind="clip",
        title="量子纠错进展",
        body="量子纠错码在表面码方案下将逻辑错误率压低了两个数量级。",
        url=None,
    )


async def _make_answer(db, text: str) -> tuple[str, str]:
    """创建会话 + 一条带引用的 assistant 回答，返回 (threadId, messageId)。"""
    store = AgentStore(db)
    thread = await store.create_thread()
    message = await store.append_message(
        thread["id"],
        role="assistant",
        content={"text": text},
        citations=[_REF],
    )
    return thread["id"], message["id"]


def test_answers_to_note_structure_and_provenance(client):
    db = client.app.state.db
    run(_seed_clip(db))
    thread_id, message_id = run(
        _make_answer(db, "表面码把逻辑错误率压低了两个数量级 [1]。")
    )
    response = client.post(
        "/api/v1/rag/answers-to-note",
        json={
            "threadId": thread_id,
            "selectedCitationIds": [message_id],
            "title": "量子纠错证据笔记",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    note_id = body["noteId"]
    content = body["contentMd"]
    # 三段式结构
    assert "## 摘录" in content
    assert "## 生成内容" in content
    assert "## 人工修改" in content
    # 摘录段 = 精确原文 + ref
    assert "量子纠错码在表面码方案下" in content
    assert _REF in content
    # 生成内容段带 AI 生成标注
    assert "AI 生成" in content
    assert "表面码把逻辑错误率压低" in content

    # -- provenance：编辑证据笔记 → 上一版入台账 ------------------------
    detail = client.get(f"/api/v1/library/notes/{note_id}")
    assert detail.status_code == 200
    base_updated_at = detail.json()["updatedAt"]
    patched = client.patch(
        f"/api/v1/library/notes/{note_id}",
        json={
            "contentMd": "## 摘录\n\n- 「人工核对后的摘录」\n\n## 生成内容\n\n> 保留\n\n## 人工修改\n\n- 补充：人工复核结论。",
            "baseUpdatedAt": base_updated_at,
        },
    )
    assert patched.status_code == 200, patched.text

    async def _revisions():
        from lumirss.lumi_notes_lifecycle import NoteLifecycleStore

        return await NoteLifecycleStore(db).list_note_revisions(note_id)

    revisions = run(_revisions())
    assert len(revisions) == 1
    assert "AI 生成" in revisions[0]["contentMd"]  # 上一版（生成内容）保留
    assert revisions[0]["origin"] == "edit"

    # 普通手写笔记编辑不入台账
    created = client.post(
        "/api/v1/library/notes",
        json={"title": "手写", "contentMd": "# 手写笔记"},
    )
    manual_id = created.json()["uuid"]
    manual_detail = client.get(f"/api/v1/library/notes/{manual_id}").json()
    client.patch(
        f"/api/v1/library/notes/{manual_id}",
        json={"contentMd": "# 改过", "baseUpdatedAt": manual_detail["updatedAt"]},
    )

    async def _manual_revisions():
        from lumirss.lumi_notes_lifecycle import NoteLifecycleStore

        return await NoteLifecycleStore(db).list_note_revisions(manual_id)

    assert run(_manual_revisions()) == []


def test_answers_to_note_rejects_foreign_or_missing_messages(client):
    db = client.app.state.db
    run(_seed_clip(db))
    thread_id, message_id = run(_make_answer(db, "回答甲 [1]。"))
    _other_thread, other_message = run(_make_answer(db, "回答乙 [1]。"))

    # 别的会话的消息 id → 422（不跨会话取「答案」）
    response = client.post(
        "/api/v1/rag/answers-to-note",
        json={
            "threadId": thread_id,
            "selectedCitationIds": [other_message],
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["type"] == "citation_invalid"

    # 未知会话 → 404
    response = client.post(
        "/api/v1/rag/answers-to-note",
        json={
            "threadId": "no-such-thread",
            "selectedCitationIds": [message_id],
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "thread_not_found"
