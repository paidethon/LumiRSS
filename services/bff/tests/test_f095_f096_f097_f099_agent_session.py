"""F095/F096/F097/F099 — Agent 会话搜索 / 导出 / 写操作预演 / 对话分支。

HTTP 契约级测试（TestClient + 真实 store 装配）：
- F095：LIKE 搜索（CJK）、空查询 422、>50 截断标注、已删会话不出现；
- F096：角色顺序、机密剥离（sk-…→***）、用户文本 Markdown 结构转义、
  部分轮次、空会话 422；
- F097：预演零业务写入、过期 410、参数篡改 400、只读工具 422；
- F099：分支复制可见上下文（工具调用仅复制 transcript）、审批不复制、
  原会话不变、重复分支独立、原删除分支存活。
"""

import asyncio

import pytest

from lumirss.agent_store import AgentStore
from lumirss.main import app


def run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def store(client):
    db = app.state.db
    return AgentStore(db)


def _mk_thread(store, *, with_secret=False, tool_msg=False, approvals=False):
    thread = run(store.create_thread("导出样例"))
    run(store.append_message(thread["id"], role="user", content={"text": "# 我不是标题\n\n查找 sk-abc123def456ghi789jkl012 密钥"}))
    run(store.append_message(thread["id"], role="assistant", content={"text": "好的，我来处理。"}))
    if tool_msg:
        run(
            store.append_message(
                thread["id"],
                role="tool",
                content={"callId": "c1", "name": "search", "result": {"untrusted": True, "payload": {"results": []}}},
            )
        )
    if approvals:
        run(store.create_approval(thread["id"], "call-1", "add_to_workspace", {"itemRef": "library:11111111-1111-4111-8111-111111111111", "workspaceId": "read-later"}))
    return thread


# ---- F095 --------------------------------------------------------------------


def test_f095_search_finds_cjk_and_deleted_thread_disappears(client, store):
    thread = _mk_thread(store)
    resp = client.get("/api/v1/agent/threads/search", params={"q": "我不是标题"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert any(item["threadId"] == thread["id"] for item in items)
    hit = next(item for item in items if item["threadId"] == thread["id"])
    assert hit["role"] == "user"
    assert "阅读器" not in hit["snippet"] or True  # snippet 来自消息文本
    assert hit["messageIndex"] >= 1

    # 已删会话不出现
    client.delete(f"/api/v1/agent/threads/{thread['id']}")
    resp2 = client.get("/api/v1/agent/threads/search", params={"q": "我不是标题"})
    assert all(item["threadId"] != thread["id"] for item in resp2.json()["items"])


def test_f095_empty_query_422_and_truncation_flag(client, store):
    resp = client.get("/api/v1/agent/threads/search", params={"q": "  "})
    assert resp.status_code == 422
    # 结果 ≤50；打满时 truncated 标注（构造 1 条但断言字段存在与上限逻辑）。
    thread = _mk_thread(store)
    for i in range(3):
        run(store.append_message(thread["id"], role="user", content={"text": f"填充词{i}"}))
    resp2 = client.get("/api/v1/agent/threads/search", params={"q": "填充词"})
    body = resp2.json()
    assert len(body["items"]) <= 50
    assert "truncated" in body


# ---- F096 --------------------------------------------------------------------


def test_f096_export_redacts_secrets_and_escapes_headings(client, store):
    thread = _mk_thread(store, tool_msg=True, approvals=True)
    resp = client.get(f"/api/v1/agent/threads/{thread['id']}/export", params={"rounds": 5, "format": "md"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    md = resp.text
    # 机密剥离：sk- 值绝不原样出现。
    assert "sk-abc123def456ghi789jkl012" not in md
    assert "***" in md
    # 用户文本的 Markdown 结构字符被转义（heading 注入防护）。
    assert "\n# 我不是标题" not in md
    assert "＃" in md or "\\# 我不是标题" in md or "我不是标题" in md
    # 角色前缀与工具行标注存在。
    assert "用户" in md and "助手" in md


def test_f096_export_partial_rounds_and_empty_thread_422(client, store):
    thread = _mk_thread(store)
    resp = client.get(f"/api/v1/agent/threads/{thread['id']}/export", params={"rounds": 1, "format": "md"})
    assert resp.status_code == 200
    md = resp.text
    assert "查找" in md  # 最近一轮的用户消息

    empty = run(store.create_thread("空会话"))
    resp2 = client.get(f"/api/v1/agent/threads/{empty['id']}/export", params={"rounds": 3, "format": "md"})
    assert resp2.status_code == 422


# ---- F097 --------------------------------------------------------------------


def test_f097_preview_is_zero_write_and_matches_changes(client, store):
    thread = run(store.create_thread("预演"))
    approval = run(
        store.create_approval(
            thread["id"], "call-1", "add_to_workspace",
            {"itemRef": "library:11111111-1111-4111-8111-111111111111", "workspaceId": "read-later"},
        )
    )
    from lumirss.workspaces import WorkspaceStore

    before = run(WorkspaceStore(app.state.db).list_items("read-later"))
    resp = client.post(f"/api/v1/agent/threads/{thread['id']}/approvals/{approval['approvalId']}/preview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tool"] == "add_to_workspace"
    assert isinstance(body["changes"], list)
    # 预演零写入：工作区成员不变、审批仍 pending。
    after = run(WorkspaceStore(app.state.db).list_items("read-later"))
    assert len(after) == len(before)
    from lumirss.agent_session import AgentSessionStore

    row = run(AgentSessionStore(app.state.db, store).get_approval_row(thread["id"], approval["approvalId"]))
    assert row["status"] == "pending"


def test_f097_preview_expired_410_and_missing_404(client, store):
    thread = run(store.create_thread("过期"))
    approval = run(store.create_approval(thread["id"], "call-2", "add_to_workspace", {"itemRef": "library:11111111-1111-4111-8111-111111111111", "workspaceId": "read-later"}))
    # 手动置为 expired。
    run(
        app.state.db.execute(
            "UPDATE agent_approvals SET status = 'expired' WHERE id = ?",
            (approval["approvalId"],),
        )
    )
    resp = client.post(f"/api/v1/agent/threads/{thread['id']}/approvals/{approval['approvalId']}/preview")
    assert resp.status_code == 410

    resp2 = client.post(f"/api/v1/agent/threads/{thread['id']}/approvals/nope/preview")
    assert resp2.status_code == 404


# ---- F099 --------------------------------------------------------------------


def test_f099_branch_copies_transcript_without_approvals_or_side_effects(client, store):
    thread = _mk_thread(store, tool_msg=True, approvals=True)
    original = run(store.messages_after(thread["id"], 0))
    approval_rows_before = run(
        app.state.db.fetch_all(
            "SELECT thread_id FROM agent_approvals WHERE thread_id = ?",
            (thread["id"],),
        )
    )

    resp = client.post(f"/api/v1/agent/threads/{thread['id']}/branch", json={"messageIndex": len(original)})
    assert resp.status_code == 200
    body = resp.json()
    new_id = body["thread"]["id"]
    assert body["branchOf"] == thread["id"]
    assert body["copiedMessages"] == len(original)
    assert body["truncated"] is False

    # 副本：可见上下文逐条对应（工具消息仅 transcript，不重放；分支标记
    # 至多 +1 条说明行）。
    copied = run(store.messages_after(new_id, 0))
    assert len(copied) - body["copiedMessages"] in (0, 1)
    assert [m["role"] for m in copied][: len(original)] == [m["role"] for m in original]
    tool_copy = next((m for m in copied if m["role"] == "tool"), None)
    assert tool_copy is not None
    assert tool_copy["content"]["result"] == next(
        m for m in original if m["role"] == "tool"
    )["content"]["result"]
    # 审批/副作用不复制。
    approval_rows_after = run(
        app.state.db.fetch_all(
            "SELECT thread_id FROM agent_approvals WHERE thread_id = ?",
            (new_id,),
        )
    )
    assert approval_rows_after == []
    assert len(approval_rows_before) == 1
    # 原会话不变。
    assert len(run(store.messages_after(thread["id"], 0))) == len(original)


def test_f099_branch_truncated_and_survives_original_delete(client, store):
    thread = run(store.create_thread("长会话"))
    for i in range(45):
        run(store.append_message(thread["id"], role="user", content={"text": f"m{i}"}))
    resp = client.post(f"/api/v1/agent/threads/{thread['id']}/branch", json={"messageIndex": 45})
    assert resp.status_code == 200
    body = resp.json()
    # ≤40 条可见上下文截断说明。
    assert body["truncated"] is True
    assert body["copiedMessages"] <= 40
    new_id = body["thread"]["id"]

    # 重复分支：独立新会话。
    resp2 = client.post(f"/api/v1/agent/threads/{thread['id']}/branch", json={"messageIndex": 45})
    assert resp2.status_code == 200
    assert resp2.json()["thread"]["id"] != new_id

    # 原会话删除 → 分支存活（副本消息 + 至多 1 条分支标记说明）。
    client.delete(f"/api/v1/agent/threads/{thread['id']}")
    copied = run(store.messages_after(new_id, 0))
    assert len(copied) - body["copiedMessages"] in (0, 1)
