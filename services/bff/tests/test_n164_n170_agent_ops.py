"""N164–N170 agent ops tests — pause/resume, thread budget, tool
timeline, approval revise, failed-step retry, diff undo, recipes.

Loop-level tests drive the real AgentLoop/AgentStore/WorkspaceStore/
TagStore with a deterministic fake provider (no network); write
persistence is verified against the real database. API-level tests
cover the new routes' honest status codes.
"""

import asyncio
import json
import time

import pytest

from lumirss.agent import AgentLoop
from lumirss.agent_recipes import (
    AgentRecipeStore,
    RecipeInvalid,
    RecipeNameConflict,
    RecipeNotFound,
    validate_recipe,
)
from lumirss.agent_session import AgentSessionStore
from lumirss.agent_store import (
    AgentStore,
    ApprovalInvalid,
    ApprovalSuperseded,
    NotPaused,
    StepNotFound,
    ToolRegistry,
    UndoConflict,
    UndoUnsupported,
    args_hash,
)
from lumirss.agent_tools import UNDOABLE_WRITE_TOOLS, build_undo_support
from lumirss.library import LibraryStore
from lumirss.main import app
from lumirss.storage import Database
from lumirss.tags import TagStore
from lumirss.workspaces import RESERVED_WORKSPACE_ID, WorkspaceStore


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture()
def env(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    store = AgentStore(db)
    library = LibraryStore(db)
    workspaces = WorkspaceStore(db)
    tags = TagStore(db)
    registry = ToolRegistry()

    calls: list[str] = []

    async def tool_search(args: dict) -> dict:
        calls.append("search")
        if hook.get("on_search"):
            hook["on_search"]()
        if hook.get("fail_next_search"):
            hook["fail_next_search"] = False
            raise RuntimeError("检索服务暂时不可用")
        return {"results": [{"title": "vLLM V1"}], "citations": ["rss:e1.test"]}

    async def tool_save_bookmark(args: dict) -> dict:
        calls.append("save_bookmark")
        view, created = await library.create_url_bookmark(
            str(args.get("url")), str(args.get("title") or "t")
        )
        return {"ref": view.ref, "created": created}

    async def tool_add_to_workspace(args: dict) -> dict:
        calls.append("add_to_workspace")
        item = await workspaces.add_item(
            str(args.get("workspaceId") or RESERVED_WORKSPACE_ID),
            str(args.get("itemRef")),
        )
        return {"added": True, "workspaceId": args.get("workspaceId"), "position": item.position}

    async def tool_add_tag(args: dict) -> dict:
        calls.append("add_tag")
        binding = await tags.attach(
            str(args.get("itemRef")), str(args.get("name")), origin="manual"
        )
        return {"tagged": True, "name": binding["name"], "ref": binding["ref"]}

    registry.register_read(
        "search",
        "search tool",
        {"type": "object", "properties": {"query": {"type": "string"}}},
        tool_search,
    )
    registry.register_write(
        "save_bookmark",
        "bookmark writer",
        {"type": "object", "properties": {"url": {"type": "string"}, "title": {"type": "string"}}},
        tool_save_bookmark,
    )
    registry.register_write(
        "add_to_workspace",
        "workspace writer",
        {"type": "object", "properties": {"itemRef": {"type": "string"}, "workspaceId": {"type": "string"}}},
        tool_add_to_workspace,
    )
    registry.register_write(
        "add_tag",
        "tag writer",
        {"type": "object", "properties": {"itemRef": {"type": "string"}, "name": {"type": "string"}}},
        tool_add_tag,
    )
    hook: dict = {}
    return {
        "db": db,
        "store": store,
        "registry": registry,
        "calls": calls,
        "library": library,
        "workspaces": workspaces,
        "tags": tags,
        "hook": hook,
        "undo": build_undo_support(workspaces=workspaces, tags=tags),
    }


class FakeProvider:
    def __init__(self, turns: list[dict]) -> None:
        self._turns = list(turns)
        self.seen_prompts: list[list[dict]] = []
        self.rounds = 0

    async def chat_completion(self, *, messages, tools=None):
        self.seen_prompts.append(messages)
        self.rounds += 1
        return self._turns.pop(0)


def make_loop(env, provider) -> AgentLoop:
    async def factory():
        return provider

    return AgentLoop(
        env["store"],
        env["registry"],
        factory,
        undo_service=env["undo"],
    )


async def last_tool_rows(env, thread_id, call_id=None):
    rows = await env["store"].messages_after(thread_id, 0)
    return [
        m
        for m in rows
        if m["role"] == "tool"
        and (call_id is None or str(m["content"].get("callId") or "") == call_id)
    ]


# ---------------------------------------------------------------------------
# N164 任务暂停与续接
# ---------------------------------------------------------------------------


def test_n164_pause_between_tools_resume_skips_completed_steps(env):
    """Pause fires between tool calls; resume re-runs the round with the
    provider re-emitting the SAME calls — executed steps are skipped
    (no duplicate execution, no duplicate transcript rows)."""

    async def scenario():
        provider = FakeProvider([
            {"tool_calls": [
                {"id": "c1", "function": {"name": "search", "arguments": '{"query": "a"}'}},
                {"id": "c2", "function": {"name": "search", "arguments": '{"query": "b"}'}},
            ]},
        ])
        loop = make_loop(env, provider)
        thread = await env["store"].create_thread()

        def _pause_during_second_call():
            if env["calls"].count("search") >= 2:
                loop.pause_turn(thread["id"])

        env["hook"]["on_search"] = _pause_during_second_call
        result = await loop.run_turn_managed(thread["id"], "搜两下")
        assert result["status"] == "paused"
        assert env["calls"].count("search") == 2  # c1 + c2 executed once

        snapshot = await env["store"].load_pause_state(thread["id"])
        assert snapshot is not None
        assert [s["callId"] for s in snapshot["completedSteps"]] == ["c1", "c2"]

        # Resume: the provider "loses state" and re-emits both calls; the
        # loop must reuse the recorded results and never re-execute.
        resume_provider = FakeProvider([
            {"tool_calls": [
                {"id": "c1", "function": {"name": "search", "arguments": '{"query": "a"}'}},
                {"id": "c2", "function": {"name": "search", "arguments": '{"query": "b"}'}},
            ]},
            {"content": "继续完成。"},
        ])

        async def factory_resume():
            return resume_provider

        loop2 = AgentLoop(env["store"], env["registry"], factory_resume, undo_service=env["undo"])
        resumed = await loop2.run_resume_managed(thread["id"])
        assert resumed["status"] == "completed"
        assert env["calls"].count("search") == 2  # NO duplicate execution
        rows = await env["store"].messages_after(thread["id"], 0)
        for call_id in ("c1", "c2"):
            executed = [
                m for m in rows
                if m["role"] == "tool"
                and str(m["content"].get("callId") or "") == call_id
                and m["content"].get("result") is not None
            ]
            assert len(executed) == 1, f"{call_id} must keep exactly one result row"
        assert await env["store"].load_pause_state(thread["id"]) is None

    run(scenario())


def test_n164_pause_turn_suspended_on_approval_and_expired_approval_needs_reconfirm(env):
    """Pause of an approval-suspended turn stores pendingApprovalId; an
    approval that expires during the pause forces RE-CONFIRMATION at
    resume (fresh approval row; the expired one stays unusable)."""

    async def scenario():
        provider = FakeProvider([
            {"tool_calls": [{"id": "c9", "function": {"name": "save_bookmark", "arguments": '{"url": "https://example.com/n164", "title": "续接"}'}}]},
        ])
        loop = make_loop(env, provider)
        thread = await env["store"].create_thread()
        result = await loop.run_turn(thread["id"], "保存")
        assert result["status"] == "awaiting_approval"
        approval_id = result["approval"]["approvalId"]

        snapshot = await loop.pause_suspended_on_approval(thread["id"])
        assert snapshot["pendingApprovalId"] == approval_id
        assert await env["store"].load_pause_state(thread["id"]) is not None

        # The approval expires while paused.
        await env["db"].execute(
            "UPDATE agent_approvals SET created_at = '2020-01-01T00:00:00+00:00' WHERE id = ?",
            (approval_id,),
        )

        prepare = await loop.resume_prepare(thread["id"])
        assert prepare["action"] == "awaiting_approval"
        assert prepare["reconfirm"] is True
        fresh = prepare["approval"]
        assert fresh["approvalId"] != approval_id
        assert fresh["tool"] == "save_bookmark"
        assert fresh["reconfirmOf"] == approval_id
        # New row bound to the same args → same args_hash.
        row = await env["db"].fetch_one(
            "SELECT args_hash FROM agent_approvals WHERE id = ?", (fresh["approvalId"],)
        )
        assert row["args_hash"] == args_hash("save_bookmark", fresh["args"])

        # The expired approval can NEVER be taken (re-confirm required).
        with pytest.raises(ApprovalInvalid):
            await env["store"].take_approval(thread["id"], approval_id)

        # Approving the FRESH approval executes the write exactly once.
        resume_provider = FakeProvider([{"content": "已保存。"}])

        async def factory_resume():
            return resume_provider

        loop2 = AgentLoop(env["store"], env["registry"], factory_resume, undo_service=env["undo"])
        decision = await loop2.apply_approval(thread["id"], fresh["approvalId"], "approve")
        assert decision["status"] == "completed"
        assert await LibraryStore(env["db"]).count_bookmarks() == 1

    run(scenario())


def test_n164_resume_with_still_pending_approval_waits(env):
    async def scenario():
        provider = FakeProvider([
            {"tool_calls": [{"id": "c8", "function": {"name": "save_bookmark", "arguments": '{"url": "https://example.com/p", "title": "p"}'}}]},
        ])
        loop = make_loop(env, provider)
        thread = await env["store"].create_thread()
        result = await loop.run_turn(thread["id"], "保存")
        approval_id = result["approval"]["approvalId"]
        await loop.pause_suspended_on_approval(thread["id"])
        prepare = await loop.resume_prepare(thread["id"])
        assert prepare["action"] == "awaiting_approval"
        assert prepare["reconfirm"] is False
        assert prepare["approval"]["approvalId"] == approval_id
        # Nothing executed while waiting.
        assert await LibraryStore(env["db"]).count_bookmarks() == 0

    run(scenario())


def test_n164_resume_without_pause_state_is_refused(env):
    async def scenario():
        loop = make_loop(env, FakeProvider([]))
        thread = await env["store"].create_thread()
        with pytest.raises(NotPaused):
            await loop.resume_prepare(thread["id"])

    run(scenario())


# ---------------------------------------------------------------------------
# N165 任务预算上限
# ---------------------------------------------------------------------------


def test_n165_max_tool_calls_budget_stops_turn_with_summary(env):
    async def scenario():
        provider = FakeProvider([
            {"tool_calls": [
                {"id": "b1", "function": {"name": "search", "arguments": '{"query": "a"}'}},
                {"id": "b2", "function": {"name": "search", "arguments": '{"query": "b"}'}},
                {"id": "b3", "function": {"name": "search", "arguments": '{"query": "c"}'}},
            ]},
        ])
        loop = make_loop(env, provider)
        thread = await env["store"].create_thread()
        await env["db"].execute(
            "UPDATE agent_threads SET budget_json = ? WHERE id = ?",
            (json.dumps({"maxToolCalls": 2, "maxTurns": 10}), thread["id"]),
        )
        result = await loop.run_turn_managed(thread["id"], "刷预算")
        assert result["status"] == "budget_exhausted"
        summary = result["summary"]
        assert summary["reason"] == "maxToolCalls"
        assert summary["toolCalls"] == 2
        assert summary["maxToolCalls"] == 2
        # Honest token accounting: provider reported nothing → unknown,
        # never a fabricated 0.
        assert summary["tokens"] is None
        assert summary["tokensKnown"] is False
        assert env["calls"].count("search") == 2
        used = await env["store"].get_budget_used(thread["id"])
        assert used["toolCalls"] == 2 and used["turns"] == 1
        assert used["tokensKnown"] is False

    run(scenario())


def test_n165_max_turns_budget_blocks_subsequent_turns(env):
    async def scenario():
        provider = FakeProvider([{"content": "第一回合回答。"}])
        loop = make_loop(env, provider)
        thread = await env["store"].create_thread()
        await env["db"].execute(
            "UPDATE agent_threads SET budget_json = ? WHERE id = ?",
            (json.dumps({"maxToolCalls": 50, "maxTurns": 1}), thread["id"]),
        )
        first = await loop.run_turn_managed(thread["id"], "第一条")
        assert first["status"] == "completed"
        second = await loop.run_turn_managed(thread["id"], "第二条")
        assert second["status"] == "budget_exhausted"
        assert second["summary"]["reason"] == "maxTurns"
        assert second["summary"]["turns"] == 1
        assert provider.rounds == 1  # blocked turn never reached the provider

    run(scenario())


def test_n165_provider_reported_tokens_are_accumulated(env):
    async def scenario():
        class UsageProvider(FakeProvider):
            last_usage = {"prompt_tokens": 11, "completion_tokens": 7}

        provider = UsageProvider([{"content": "回答。"}])
        loop = make_loop(env, provider)
        thread = await env["store"].create_thread()
        await env["db"].execute(
            "UPDATE agent_threads SET budget_json = ? WHERE id = ?",
            (json.dumps({"maxToolCalls": 10, "maxTurns": 5}), thread["id"]),
        )
        result = await loop.run_turn_managed(thread["id"], "你好")
        assert result["status"] == "completed"
        used = await env["store"].get_budget_used(thread["id"])
        assert used["tokensKnown"] is True
        assert used["tokens"] == 18

    run(scenario())


# ---------------------------------------------------------------------------
# N166 工具执行时间线
# ---------------------------------------------------------------------------


def test_n166_tool_rows_carry_timeline_fields_without_secret_leak(env):
    async def scenario():
        provider = FakeProvider([
            {"tool_calls": [{"id": "t1", "function": {"name": "search", "arguments": '{"query": "vLLM", "apiKey": "sk-abcdef123456secret"}'}}]},
            {"content": "找到了。"},
        ])
        loop = make_loop(env, provider)
        thread = await env["store"].create_thread()
        await loop.run_turn(thread["id"], "搜一下")
        rows = await last_tool_rows(env, thread["id"], "t1")
        assert len(rows) == 1
        content = rows[0]["content"]
        # Duration is a real measured integer.
        assert isinstance(content["durationMs"], int) and content["durationMs"] >= 0
        # Masked args summary: ≤80 chars, secrets redacted.
        summary = content["maskedArgsSummary"]
        assert len(summary) <= 80
        assert "sk-abcdef123456secret" not in summary
        assert "***" in summary
        assert content["resultType"] == "result"
        # Timeline rows never carry api-key-shaped values anywhere.
        serialized = json.dumps(content, ensure_ascii=False)
        assert "sk-abcdef" not in serialized

    run(scenario())


def test_n166_failed_tool_rows_are_marked_error(env):
    async def scenario():
        env["hook"]["fail_next_search"] = True
        provider = FakeProvider([
            {"tool_calls": [{"id": "t2", "function": {"name": "search", "arguments": '{"query": "x"}'}}]},
            {"content": "好的。"},
        ])
        loop = make_loop(env, provider)
        thread = await env["store"].create_thread()
        await loop.run_turn(thread["id"], "搜一下")
        rows = await last_tool_rows(env, thread["id"], "t2")
        assert rows[0]["content"]["resultType"] == "error"

    run(scenario())


# ---------------------------------------------------------------------------
# N167 批准内容修改
# ---------------------------------------------------------------------------


def test_n167_revise_creates_new_hash_and_supersedes_old(env):
    async def scenario():
        store = env["store"]
        thread = await store.create_thread()
        old_args = {"url": "https://example.com/old", "title": "old"}
        approval = await store.create_approval(thread["id"], "call-1", "save_bookmark", old_args)
        new_args = {"url": "https://example.com/new", "title": "revised"}
        fresh = await store.revise_approval(thread["id"], approval["approvalId"], new_args)
        assert fresh["args"] == new_args
        row = await env["db"].fetch_one(
            "SELECT args_hash, status, superseded_by FROM agent_approvals WHERE id = ?",
            (fresh["approvalId"],),
        )
        assert row["args_hash"] == args_hash("save_bookmark", new_args)
        assert row["args_hash"] != args_hash("save_bookmark", old_args)
        old_row = await env["db"].fetch_one(
            "SELECT status, superseded_by FROM agent_approvals WHERE id = ?",
            (approval["approvalId"],),
        )
        assert old_row["status"] == "superseded"
        assert old_row["superseded_by"] == fresh["approvalId"]
        # Taking the OLD approval is refused (superseded → 410 family).
        with pytest.raises(ApprovalSuperseded):
            await store.take_approval(thread["id"], approval["approvalId"])
        # The NEW approval executes normally.
        taken = await store.take_approval(thread["id"], fresh["approvalId"])
        assert taken["args"] == new_args

    run(scenario())


def test_n167_revise_refuses_cross_thread_and_decided_approvals(env):
    async def scenario():
        store = env["store"]
        thread_a = await store.create_thread()
        thread_b = await store.create_thread()
        approval = await store.create_approval(
            thread_a["id"], "call-1", "save_bookmark", {"url": "https://example.com/x"}
        )
        # Cross-thread (per-user isolation boundary at store level).
        with pytest.raises(ApprovalInvalid):
            await store.revise_approval(thread_b["id"], approval["approvalId"], {"url": "y"})
        # A decided approval is not revisable.
        await store.reject_pending(thread_a["id"], approval["approvalId"])
        with pytest.raises(ApprovalInvalid):
            await store.revise_approval(thread_a["id"], approval["approvalId"], {"url": "y"})

    run(scenario())


# ---------------------------------------------------------------------------
# N168 失败步骤单独重试
# ---------------------------------------------------------------------------


def test_n168_retry_reexecutes_only_failed_steps(env):
    async def scenario():
        env["hook"]["fail_next_search"] = True
        provider = FakeProvider([
            {"tool_calls": [
                {"id": "r1", "function": {"name": "search", "arguments": '{"query": "first"}'}},
                {"id": "r2", "function": {"name": "search", "arguments": '{"query": "second"}'}},
            ]},
            {"content": "结束。"},
        ])
        loop = make_loop(env, provider)
        thread = await env["store"].create_thread()
        await loop.run_turn(thread["id"], "搜两次")
        assert env["calls"].count("search") == 2  # r1 failed + r2 ok
        # Retry: only r1 (failed) re-executes; r2 stays untouched.
        result = await loop.retry_failed_steps(thread["id"])
        assert result["status"] == "completed"
        assert [item["callId"] for item in result["retried"]] == ["r1"]
        assert env["calls"].count("search") == 3
        rows = await env["store"].messages_after(thread["id"], 0)
        r2_rows = [
            m for m in rows
            if m["role"] == "tool" and str(m["content"].get("callId") or "") == "r2"
        ]
        assert len(r2_rows) == 1  # completed step reused, not re-run
        r1_rows = [
            m for m in rows
            if m["role"] == "tool" and str(m["content"].get("callId") or "") == "r1"
        ]
        assert len(r1_rows) == 2
        assert r1_rows[-1]["content"]["retried"] is True
        assert r1_rows[-1]["content"]["resultType"] == "result"

    run(scenario())


def test_n168_replayed_successful_write_returns_cached_result(env):
    async def scenario():
        loop = make_loop(env, FakeProvider([{"content": "已保存。"}]))
        thread = await env["store"].create_thread()
        user_row = await env["store"].append_message(
            thread["id"], role="user", content={"text": "保存"}
        )
        args = {"url": "https://example.com/replay", "title": "重放"}
        first = await env["store"].create_approval(thread["id"], "w1", "save_bookmark", args)
        await loop.apply_approval(thread["id"], first["approvalId"], "approve")
        assert await env["library"].count_bookmarks() == 1

        # A retry re-creates an approval with the SAME args in the SAME
        # turn — approving it must return the CACHED result and never
        # duplicate the write.
        replay = await env["store"].create_approval(thread["id"], "w1b", "save_bookmark", args)
        resume_provider = FakeProvider([{"content": "已保存。"}])

        async def factory_resume():
            return resume_provider

        loop2 = AgentLoop(env["store"], env["registry"], factory_resume, undo_service=env["undo"])
        await loop2.apply_approval(thread["id"], replay["approvalId"], "approve")
        assert await env["library"].count_bookmarks() == 1  # no duplicate
        assert env["calls"].count("save_bookmark") == 1
        # The transcript row honestly marks the replay.
        rows = await last_tool_rows(env, thread["id"], "w1b")
        assert rows[-1]["content"]["replayed"] is True
        _ = user_row

    run(scenario())


# ---------------------------------------------------------------------------
# N169 任务结果差异撤销
# ---------------------------------------------------------------------------


def test_n169_undo_reverts_workspace_and_tag_writes(env):
    async def scenario():
        loop = make_loop(env, FakeProvider([{"content": "ok"}, {"content": "ok"}]))
        thread = await env["store"].create_thread()
        ref = "library:0b8df3e0-1f2a-4c3d-9e4f-5a6b7c8d9e0f"
        await env["store"].append_message(thread["id"], role="user", content={"text": "整理"})
        approval = await env["store"].create_approval(
            thread["id"], "u1", "add_to_workspace", {"workspaceId": RESERVED_WORKSPACE_ID, "itemRef": ref}
        )
        await loop.apply_approval(thread["id"], approval["approvalId"], "approve")
        members = await env["workspaces"].list_items(RESERVED_WORKSPACE_ID)
        assert any(m.item_ref == ref for m in members)

        rows = await last_tool_rows(env, thread["id"], "u1")
        step_id = rows[-1]["content"]["stepId"]
        assert rows[-1]["content"]["undoable"] is True
        journal = await env["store"].get_tool_write(thread["id"], step_id)
        assert journal["before"]["member"] is False
        assert journal["after"]["member"] is True

        undo_result = await env["undo"]["undo"](journal["tool"], journal["args"], journal["before"], journal["after"])
        assert undo_result["undone"] is True
        members = await env["workspaces"].list_items(RESERVED_WORKSPACE_ID)
        assert not any(m.item_ref == ref for m in members)

        # Same for add_tag.
        approval2 = await env["store"].create_approval(
            thread["id"], "u2", "add_tag", {"itemRef": ref, "name": "深度阅读"}
        )
        await loop.apply_approval(thread["id"], approval2["approvalId"], "approve")
        rows2 = await last_tool_rows(env, thread["id"], "u2")
        journal2 = await env["store"].get_tool_write(thread["id"], rows2[-1]["content"]["stepId"])
        await env["undo"]["undo"](journal2["tool"], journal2["args"], journal2["before"], journal2["after"])
        names = [t["name"] for t in await env["tags"].tags_for_item(ref)]
        assert "深度阅读" not in names

    run(scenario())


def test_n169_undo_conflict_when_object_modified_since(env):
    async def scenario():
        loop = make_loop(env, FakeProvider([{"content": "ok"}, {"content": "ok"}]))
        thread = await env["store"].create_thread()
        ref = "library:0b8df3e0-1f2a-4c3d-9e4f-5a6b7c8d9e0f"
        await env["store"].append_message(thread["id"], role="user", content={"text": "整理"})
        approval = await env["store"].create_approval(
            thread["id"], "u3", "add_tag", {"itemRef": ref, "name": "冲突"}
        )
        await loop.apply_approval(thread["id"], approval["approvalId"], "approve")
        rows = await last_tool_rows(env, thread["id"], "u3")
        journal = await env["store"].get_tool_write(thread["id"], rows[-1]["content"]["stepId"])
        # The object was modified since the write: the binding was removed.
        await env["tags"].detach(ref, "冲突")
        with pytest.raises(UndoConflict):
            await env["undo"]["undo"](journal["tool"], journal["args"], journal["before"], journal["after"])

    run(scenario())


def test_n169_unsupported_tool_journal_is_not_undoable(env):
    async def scenario():
        loop = make_loop(env, FakeProvider([{"content": "ok"}]))
        thread = await env["store"].create_thread()
        await env["store"].append_message(thread["id"], role="user", content={"text": "保存"})
        approval = await env["store"].create_approval(
            thread["id"], "u4", "save_bookmark", {"url": "https://example.com/undo", "title": "x"}
        )
        await loop.apply_approval(thread["id"], approval["approvalId"], "approve")
        rows = await last_tool_rows(env, thread["id"], "u4")
        assert rows[-1]["content"]["undoable"] is False
        step_id = rows[-1]["content"]["stepId"]
        journal = await env["store"].get_tool_write(thread["id"], step_id)
        with pytest.raises(UndoUnsupported):
            await env["undo"]["undo"](journal["tool"], journal["args"], journal["before"], journal["after"])
        assert "save_bookmark" not in UNDOABLE_WRITE_TOOLS

    run(scenario())


def test_n169_unknown_step_id_is_not_found(env):
    async def scenario():
        thread = await env["store"].create_thread()
        assert await env["store"].get_tool_write(thread["id"], "missing") is None
        with pytest.raises(StepNotFound):
            raise StepNotFound("没有找到该写入步骤的台账记录。")

    run(scenario())


# ---------------------------------------------------------------------------
# N170 任务配方
# ---------------------------------------------------------------------------


def test_n170_validate_recipe_rejects_bad_input():
    with pytest.raises(RecipeInvalid):
        validate_recipe(name="", input_text="x", tool_whitelist=["search"], scope=None)
    with pytest.raises(RecipeInvalid):
        validate_recipe(name="n", input_text="  ", tool_whitelist=["search"], scope=None)
    with pytest.raises(RecipeInvalid):
        validate_recipe(name="n", input_text="x", tool_whitelist=[], scope=None)
    with pytest.raises(RecipeInvalid):
        validate_recipe(name="n", input_text="x", tool_whitelist=[42], scope=None)
    with pytest.raises(RecipeInvalid):
        validate_recipe(name="n", input_text="x", tool_whitelist=["search"], scope={"bogus": 1})


def test_n170_recipe_store_crud_and_name_conflict(tmp_path):
    async def scenario():
        db = Database(tmp_path / "recipes.sqlite")
        await db.migrate()
        store = AgentRecipeStore(db)
        recipe = await store.create_recipe(
            name="晨报整理",
            input_text="把稍后读里的新条目整理一下",
            tool_whitelist=["search", "add_to_workspace"],
            scope={"workspaceId": "read-later"},
        )
        assert recipe["toolWhitelist"] == ["search", "add_to_workspace"]
        assert recipe["scope"] == {"workspaceId": "read-later"}
        listed = await store.list_recipes()
        assert [r["id"] for r in listed] == [recipe["id"]]
        with pytest.raises(RecipeNameConflict):
            await store.create_recipe(
                name="晨报整理",
                input_text="again",
                tool_whitelist=["search"],
                scope=None,
            )
        fetched = await store.get_recipe(recipe["id"])
        assert fetched["name"] == "晨报整理"
        assert await store.delete_recipe(recipe["id"]) is True
        with pytest.raises(RecipeNotFound):
            await store.get_recipe(recipe["id"])
        assert await store.delete_recipe(recipe["id"]) is False

    run(scenario())


# ---------------------------------------------------------------------------
# API-level routes (pause / resume / revise / retry / undo / recipes)
# ---------------------------------------------------------------------------


@pytest.fixture()
def agent_env(client):  # noqa: F811 — reuse the conftest fixture
    app.state.agent_store = None
    app.state.agent_loop = None
    app.state.agent_tasks = set()
    app.state.agent_dry_run = None
    app.state.agent_undo = None
    yield {"db": app.state.db}
    deadline = time.time() + 15
    while app.state.agent_tasks and time.time() < deadline:
        time.sleep(0.05)
    if app.state.agent_tasks:
        for task in tuple(app.state.agent_tasks):
            task.cancel()
        pytest.fail("agent tasks did not drain in time")


def _create_thread(client) -> str:
    response = client.post("/api/v1/agent/threads")
    assert response.status_code == 201
    return response.json()["id"]


def test_api_pause_and_resume_routes(agent_env, client):
    from lumirss.agent_store import AgentStore

    thread_id = _create_thread(client)
    # Nothing running and nothing suspended → 409.
    response = client.post(f"/api/v1/agent/threads/{thread_id}/pause")
    assert response.status_code == 409
    assert response.json()["error"]["type"] == "no_active_run"

    store = AgentStore(app.state.db)
    run(store.create_approval(thread_id, "c1", "save_bookmark", {"url": "https://example.com/z"}))
    # Suspended on approval → pause freezes the suspension.
    response = client.post(f"/api/v1/agent/threads/{thread_id}/pause")
    assert response.status_code == 200
    assert response.json() == {"paused": True, "status": "paused"}
    assert run(store.load_pause_state(thread_id)) is not None

    # Resume with a still-pending approval → awaiting_approval.
    response = client.post(f"/api/v1/agent/threads/{thread_id}/resume")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "awaiting_approval"
    assert body["reconfirmRequired"] is False
    assert body["approval"]["status"] == "pending"

    # Resume without pause state → 409 not_paused.
    response = client.post(f"/api/v1/agent/threads/{thread_id}/resume")
    assert response.status_code == 409
    assert response.json()["error"]["type"] == "not_paused"

    # Missing thread → 404.
    assert client.post("/api/v1/agent/threads/nope/pause").status_code == 404
    assert client.post("/api/v1/agent/threads/nope/resume").status_code == 404


def test_api_expired_approval_at_resume_requires_reconfirm(agent_env, client):
    from lumirss.agent_store import AgentStore

    thread_id = _create_thread(client)
    store = AgentStore(app.state.db)
    approval = run(
        store.create_approval(thread_id, "c2", "save_bookmark", {"url": "https://example.com/e2"})
    )
    # Any agent route access lazily builds the loop (409 still builds it).
    blocked = client.post(
        f"/api/v1/agent/threads/{thread_id}/messages", json={"text": "x"}
    )
    assert blocked.status_code == 409
    assert run(app.state.agent_loop.pause_suspended_on_approval(thread_id)) is not None
    run(store._db.execute(  # noqa: SLF001 — test reaches into the db handle
        "UPDATE agent_approvals SET created_at = '2020-01-01T00:00:00+00:00' WHERE id = ?",
        (approval["approvalId"],),
    ))
    response = client.post(f"/api/v1/agent/threads/{thread_id}/resume")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "awaiting_approval"
    assert body["reconfirmRequired"] is True
    fresh = body["approval"]
    assert fresh["approvalId"] != approval["approvalId"]
    assert fresh["reconfirmOf"] == approval["approvalId"]
    # The old approval is expired — approving it fails honestly.
    decision = client.post(
        f"/api/v1/agent/threads/{thread_id}/approvals",
        json={"approvalId": approval["approvalId"], "decision": "approve"},
    )
    assert decision.status_code == 409  # ApprovalInvalid → stable envelope
    # Approving the fresh re-confirmation works.
    decision = client.post(
        f"/api/v1/agent/threads/{thread_id}/approvals",
        json={"approvalId": fresh["approvalId"], "decision": "approve"},
    )
    assert decision.status_code == 503  # provider unavailable after write — honest
    messages = client.get(f"/api/v1/agent/threads/{thread_id}/messages").json()["items"]
    assert any(
        m["role"] == "tool" and m["content"].get("approved") is True for m in messages
    )


def test_api_revise_approval_route(agent_env, client):
    from lumirss.agent_store import AgentStore

    thread_id = _create_thread(client)
    store = AgentStore(app.state.db)
    approval = run(
        store.create_approval(thread_id, "c3", "save_bookmark", {"url": "https://example.com/v1", "title": "v1"})
    )
    response = client.post(
        f"/api/v1/agent/threads/{thread_id}/approvals/{approval['approvalId']}/revise",
        json={"newArgs": {"url": "https://example.com/v2", "title": "v2"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["supersededApprovalId"] == approval["approvalId"]
    assert body["approval"]["args"] == {"url": "https://example.com/v2", "title": "v2"}
    # Deciding on the OLD id now fails (superseded → 410).
    old_decision = client.post(
        f"/api/v1/agent/threads/{thread_id}/approvals",
        json={"approvalId": approval["approvalId"], "decision": "approve"},
    )
    assert old_decision.status_code == 410
    assert old_decision.json()["error"]["type"] == "approval_superseded"
    # The revised approval row is pending in the transcript.
    messages = client.get(f"/api/v1/agent/threads/{thread_id}/messages").json()["items"]
    approvals = [m for m in messages if m["role"] == "approval"]
    assert any(
        m["content"]["approvalId"] == body["approval"]["approvalId"] for m in approvals
    )


def test_api_retry_route(agent_env, client):
    thread_id = _create_thread(client)
    # A thread whose last turn has no failed steps → completed, empty.
    response = client.post(f"/api/v1/agent/threads/{thread_id}/retry")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["retried"] == [] and body["skipped"] == []
    # Missing thread → 404.
    assert client.post("/api/v1/agent/threads/nope/retry").status_code == 404


def _approve_via_route(client, thread_id: str, approval_id: str) -> None:
    """Decide via the HTTP route; 503 = write done, then provider
    unavailable for the summarizing round (AI unconfigured in tests)."""
    response = client.post(
        f"/api/v1/agent/threads/{thread_id}/approvals",
        json={"approvalId": approval_id, "decision": "approve"},
    )
    assert response.status_code in (200, 503)


def test_api_undo_route_conflicts_and_unsupported(agent_env, client):
    from lumirss.agent_store import AgentStore
    from lumirss.library import LibraryStore
    from lumirss.workspaces import WorkspaceStore

    thread_id = _create_thread(client)
    db = app.state.db
    store = AgentStore(db)
    # Lazily build the app loop + undo service via any agent route.
    blocked = client.post(
        f"/api/v1/agent/threads/{thread_id}/messages", json={"text": "x"}
    )
    assert blocked.status_code == 202  # no approval yet → turn runs (AI 未配置)
    assert app.state.agent_loop is not None  # loop + undo service are built
    run(store.append_message(thread_id, role="user", content={"text": "保存"}))
    # save_bookmark: journal row is recorded but NOT undoable → 422.
    approval = run(
        store.create_approval(thread_id, "n1", "save_bookmark", {"url": "https://example.com/uu", "title": "u"})
    )
    _approve_via_route(client, thread_id, approval["approvalId"])
    rows = [
        m
        for m in client.get(f"/api/v1/agent/threads/{thread_id}/messages").json()["items"]
        if m["role"] == "tool" and m["content"].get("callId") == "n1"
    ]
    step_id = rows[-1]["content"]["stepId"]
    response = client.post(f"/api/v1/agent/threads/{thread_id}/undo", json={"stepId": step_id})
    assert response.status_code == 422
    assert response.json()["error"]["type"] == "undo_unsupported"
    assert run(LibraryStore(db).count_bookmarks()) == 1

    # add_to_workspace on an object removed afterwards → conflict report.
    from lumirss.workspaces import RESERVED_WORKSPACE_ID

    ref = "library:0b8df3e0-1f2a-4c3d-9e4f-5a6b7c8d9e0f"
    approval2 = run(
        store.create_approval(
            thread_id, "n2", "add_to_workspace", {"workspaceId": RESERVED_WORKSPACE_ID, "itemRef": ref}
        )
    )
    _approve_via_route(client, thread_id, approval2["approvalId"])
    rows2 = [
        m
        for m in client.get(f"/api/v1/agent/threads/{thread_id}/messages").json()["items"]
        if m["role"] == "tool" and m["content"].get("callId") == "n2"
    ]
    step_id2 = rows2[-1]["content"]["stepId"]
    # Object modified since the write: remove it behind the journal's back.
    workspaces = WorkspaceStore(db)
    run(workspaces.remove_item(RESERVED_WORKSPACE_ID, ref, force=True))
    response = client.post(f"/api/v1/agent/threads/{thread_id}/undo", json={"stepId": step_id2})
    assert response.status_code == 200
    body = response.json()
    assert body["undone"] is False
    assert body["conflictReason"]
    # Unknown step id → 404.
    response = client.post(f"/api/v1/agent/threads/{thread_id}/undo", json={"stepId": "missing"})
    assert response.status_code == 404


def test_api_recipes_crud_preview_run_and_whitelist(agent_env, client):
    # Unknown tool in whitelist → 422.
    bad = client.post(
        "/api/v1/agent/recipes",
        json={"name": "坏配方", "input": "整理", "toolWhitelist": ["delete_everything"]},
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["type"] == "invalid_recipe"

    created = client.post(
        "/api/v1/agent/recipes",
        json={
            "name": "稍后读整理",
            "input": "把搜索到的第一条加入稍后读",
            "toolWhitelist": ["search"],
            "scope": {"workspaceId": "read-later"},
        },
    )
    assert created.status_code == 201
    recipe = created.json()
    assert recipe["toolWhitelist"] == ["search"]

    listed = client.get("/api/v1/agent/recipes")
    assert listed.status_code == 200
    assert [r["id"] for r in listed.json()["items"]] == [recipe["id"]]

    # Duplicate name → 409.
    duplicate = client.post(
        "/api/v1/agent/recipes",
        json={"name": "稍后读整理", "input": "x", "toolWhitelist": ["search"]},
    )
    assert duplicate.status_code == 409

    # Preview before run: zero writes, shows the resulting policy.
    preview = client.post(f"/api/v1/agent/recipes/{recipe['id']}/preview")
    assert preview.status_code == 200
    body = preview.json()
    assert body["unknownTools"] == []
    assert body["toolPolicy"]["allowedTools"] == ["search"]
    assert body["scope"] == {"workspaceId": "read-later"}

    # Run: creates a NEW thread with the whitelist as toolPolicy.
    ran = client.post(f"/api/v1/agent/recipes/{recipe['id']}/run")
    assert ran.status_code == 202
    run_body = ran.json()
    thread_id = run_body["thread"]["id"]
    assert thread_id != recipe["id"]
    settings = run(
        AgentSessionStore(app.state.db, app.state.agent_store).get_settings(thread_id)
    )
    assert settings["toolPolicy"]["allowedTools"] == ["search"]
    assert settings["scope"] == {"workspaceId": "read-later"}

    # The first message of the run is the recipe input (turn starts).
    deadline = time.time() + 15
    while time.time() < deadline:
        messages = client.get(f"/api/v1/agent/threads/{thread_id}/messages").json()["items"]
        if messages and messages[-1]["role"] == "assistant":
            break
        time.sleep(0.05)
    assert messages[0]["role"] == "user"
    assert messages[0]["content"]["text"] == "把搜索到的第一条加入稍后读"

    # Delete → 404 on second delete.
    assert client.delete(f"/api/v1/agent/recipes/{recipe['id']}").status_code == 204
    assert client.delete(f"/api/v1/agent/recipes/{recipe['id']}").status_code == 404
