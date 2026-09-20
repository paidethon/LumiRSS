"""F094 会话资料范围锁定 / F098 会话权限收窄 — 服务端过滤、只读写拒、
allowed_tools 子集、审批不能复活被禁工具、下轮生效、重启持久。"""

import asyncio

import pytest

from lumirss.agent import AgentLoop
from lumirss.agent_scope import allowed_refs_for_scope
from lumirss.agent_session import (
    AgentSessionStore,
    evaluate_policy,
)
from lumirss.agent_store import AgentStore
from lumirss.agent_tools import build_registry
from lumirss.library import LibraryStore
from lumirss.main import app
from lumirss.search_library import LibrarySearchWriter
from lumirss.tags import TagStore
from lumirss.workspaces import WorkspaceStore

# 规范 UUID 形式的 library ItemRef（parse_item_ref 要求 canonical uuid）。
DOC_A = "library:11111111-1111-4111-8111-111111111111"
DOC_B = "library:22222222-2222-4222-8222-222222222222"


def run(coro):
    return asyncio.run(coro)


class FakeProvider:
    def __init__(self, turns):
        self._turns = list(turns)

    async def chat_completion(self, *, messages, tools=None):
        return self._turns.pop(0)


@pytest.fixture()
def scope_env(client, monkeypatch):
    app.state.agent_store = None
    app.state.agent_loop = None
    db = app.state.db
    store = AgentStore(db)
    registry = build_registry(
        db=db,
        rss_search=lambda q, limit=5: _rss_noop(),
        library_search=LibrarySearchWriter(db),
        rag=object(),
        adapter=None,
        library=LibraryStore(db),
        workspaces=WorkspaceStore(db),
        tags=TagStore(db),
    )
    async def factory():
        return None

    async def rss_search(query, limit=5):
        return [
            {"entry_ref": DOC_A, "title": "同名条目", "content_text": "跨工作区同名条目 A"},
            {"entry_ref": DOC_B, "title": "同名条目", "content_text": "跨工作区同名条目 B"},
        ]

    registry = build_registry(
        db=db,
        rss_search=rss_search,
        library_search=LibrarySearchWriter(db),
        rag=object(),
        adapter=None,
        library=LibraryStore(db),
        workspaces=WorkspaceStore(db),
        tags=TagStore(db),
    )
    session = AgentSessionStore(db, store)
    loop = AgentLoop(store, registry, factory, session_loader=session.get_settings)
    # 库内索引种子：DOC_B 是可被全文命中的 library 行（DOC_A 仅在工作区成员关系里）。
    run(
        LibrarySearchWriter(db).upsert(
            ref=DOC_B,
            kind="bookmark",
            title="同名条目",
            body="跨工作区同名条目 B",
            url=None,
        )
    )
    try:
        yield {"db": db, "store": store, "registry": registry, "loop": loop, "session": session}
    finally:
        app.state.agent_store = None
        app.state.agent_loop = None


async def _rss_noop():
    return []


def test_f094_scope_filters_tools_server_side(scope_env):
    env = scope_env
    ws = run(WorkspaceStore(env["db"]).create_workspace("范围工作区")).id
    run(WorkspaceStore(env["db"]).add_item(ws, DOC_A))
    scope = {"workspaceId": ws}
    allowed = run(allowed_refs_for_scope(env["db"], WorkspaceStore(env["db"]), scope))
    assert allowed == {DOC_A}
    # 工具执行：范围内仅 DOC_A 命中（跨工作区同名条目仅范围内命中）
    env["registry"].set_context({"scope": scope})
    result = run(env["registry"].invoke_read("search", {"query": "同名条目"}))
    assert result["citations"] == [DOC_A]
    # 未锁定行为不变（两条都返回）
    env["registry"].set_context({})
    result_all = run(env["registry"].invoke_read("search", {"query": "同名条目"}))
    assert set(result_all["citations"]) == {DOC_A, DOC_B}
    # 空范围 → 诚实报错
    env["registry"].set_context({"scope": {"entryRefs": []}})
    empty = run(env["registry"].invoke_read("search", {"query": "同名条目"}))
    assert empty.get("error") == "scope_empty"
    # 范围是会话级：直接查询（不经工具上下文）不受影响 —— 范围外的 DOC_B 仍可命中
    rows = run(LibrarySearchWriter(env["db"]).search("同名条目"))
    assert [row["ref"] for row in rows] == [DOC_B]


def test_f094_scope_change_takes_effect_next_turn(scope_env):
    env = scope_env
    ws = run(WorkspaceStore(env["db"]).create_workspace("下轮生效")).id
    run(WorkspaceStore(env["db"]).add_item(ws, DOC_A))
    thread = run(env["store"].create_thread())
    # 第一轮：无范围 → 两条
    provider = FakeProvider([
        {"tool_calls": [{"id": "c1", "function": {"name": "search", "arguments": '{"query": "同名条目"}'}}]},
        {"content": "未锁定，找到两条。"},
    ])
    env["loop"]._provider_factory = make_factory(provider)  # noqa: SLF001
    run(env["loop"].run_turn(thread["id"], "搜一下"))
    messages = run(env["store"].messages_after(thread["id"], 0))
    tool_payload = next(m for m in messages if m["role"] == "tool")["content"]
    # 未锁定：A、B 都命中（rss 两条 + 库内 DOC_B 投影行 → 3 条结果）
    results = tool_payload["result"]["payload"]["results"]
    assert len(results) == 3
    assert any("条目 A" in r["snippet"] for r in results)
    assert any("条目 B" in r["snippet"] for r in results)
    # 设置范围（下轮生效）
    run(env["session"].update_settings(thread["id"], scope={"workspaceId": ws}))
    provider2 = FakeProvider([
        {"tool_calls": [{"id": "c2", "function": {"name": "search", "arguments": '{"query": "同名条目"}'}}]},
        {"content": "范围锁定，一条。"},
    ])
    env["loop"]._provider_factory = make_factory(provider2)  # noqa: SLF001
    run(env["loop"].run_turn(thread["id"], "再搜一次"))
    messages2 = run(env["store"].messages_after(thread["id"], 0))
    tool2 = [m for m in messages2 if m["role"] == "tool"][-1]["content"]
    assert len(tool2["result"]["payload"]["results"]) == 1
    # 重启持久：新 session store 读取范围仍在
    fresh = AgentSessionStore(env["db"], env["store"])
    settings = run(fresh.get_settings(thread["id"]))
    assert settings["scope"] == {"workspaceId": ws}


def make_factory(provider):
    async def factory():
        return provider

    return factory


def test_f098_readonly_blocks_write_and_allowed_tools_subset(scope_env):
    env = scope_env
    thread = run(env["store"].create_thread())
    run(
        env["session"].update_settings(
            thread["id"],
            tool_policy={"mode": "readonly", "allowedTools": ["search"]},
        )
    )
    provider = FakeProvider([
        {"tool_calls": [
            {"id": "w1", "function": {"name": "add_to_workspace", "arguments": f'{{"itemRef": "{DOC_A}"}}'}},
            {"id": "r1", "function": {"name": "rag_search", "arguments": '{"query": "x"}'}},
            {"id": "r2", "function": {"name": "search", "arguments": '{"query": "同名条目"}'}},
        ]},
        {"content": "完成。"},
    ])
    env["loop"]._provider_factory = make_factory(provider)  # noqa: SLF001
    result = run(env["loop"].run_turn(thread["id"], "帮我加工作区"))
    assert result["status"] == "completed"
    messages = run(env["store"].messages_after(thread["id"], 0))
    tool_msgs = [m for m in messages if m["role"] == "tool"]
    denied = {m["content"]["callId"]: m["content"].get("error") for m in tool_msgs if "error" in m["content"]}
    # 服务端拒绝：写工具 readonly → tool_denied；rag_search 不在 allowed → tool_denied
    assert denied.get("w1") == "tool_denied"
    assert denied.get("r1") == "tool_denied"
    assert "w1" not in {m["content"].get("callId") for m in tool_msgs if m["content"].get("result")}
    # 无 pending 审批（写从未进入审批流）
    assert run(env["store"].has_pending_approval(thread["id"])) is False
    # evaluate_policy 纯函数
    assert evaluate_policy({"mode": "readonly"}, "add_to_workspace", is_write=True) == "readonly_mode"
    assert evaluate_policy({"allowedTools": ["search"]}, "rag_search", is_write=False) == "tool_not_allowed"
    assert evaluate_policy(None, "add_to_workspace", is_write=True) is None


def test_f098_approved_write_denied_after_narrowing(scope_env):
    """负向：既有已批准 write 审批在收窄后执行被拒（审批不能复活被禁工具）。"""
    env = scope_env
    thread = run(env["store"].create_thread())
    # 收窄前：批准并挂起写入
    approval = run(
        env["store"].create_approval(
            thread["id"], "call-1", "add_to_workspace", {"itemRef": DOC_A, "workspaceId": "read-later"}
        )
    )
    run(env["session"].update_settings(thread["id"], tool_policy={"mode": "readonly"}))
    result = run(env["loop"].apply_approval(thread["id"], approval["approvalId"], "approve"))
    assert result["status"] == "tool_denied"
    # 工作区未被写入（负向）
    members = run(WorkspaceStore(env["db"]).list_items("read-later"))
    assert all(m.item_ref != DOC_A for m in members)
    # settings 持久
    settings = run(env["session"].get_settings(thread["id"]))
    assert settings["toolPolicy"]["mode"] == "readonly"


def test_f098_max_ops_truncation_and_http_patch(client):
    thread = client.post("/api/v1/agent/threads").json()["id"]
    patch = client.patch(
        f"/api/v1/agent/threads/{thread}",
        json={"toolPolicy": {"mode": "all", "maxOpsPerTurn": 2}},
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["toolPolicy"]["maxOpsPerTurn"] == 2
    # 非法策略 → 422
    bad = client.patch(
        f"/api/v1/agent/threads/{thread}",
        json={"toolPolicy": {"maxOpsPerTurn": 99}},
    )
    assert bad.status_code == 422
    # F094 PATCH scope
    scope_patch = client.patch(
        f"/api/v1/agent/threads/{thread}",
        json={"scope": {"entryRefs": ["library:x"]}},
    )
    assert scope_patch.status_code == 200
    assert scope_patch.json()["scope"] == {"entryRefs": ["library:x"]}
    cleared = client.patch(
        f"/api/v1/agent/threads/{thread}", json={"clearScope": True}
    )
    assert cleared.status_code == 200
    assert cleared.json()["scope"] is None
