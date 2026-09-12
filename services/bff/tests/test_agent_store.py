"""AgentStore hardening tests (P0-08e + approval races).

Concurrency semantics: atomic one-time approval claim (rowcount-gated
UPDATE inside a transaction), row-bound args (no message-log
re-derivation), cross-thread isolation, expiry, restart sweep of
orphaned run markers, and per-thread message seq serialization.
"""

import asyncio

import pytest

from lumirss.agent_store import (
    INTERRUPTED_TEXT,
    AgentStore,
    ApprovalInvalid,
    args_hash,
)
from lumirss.library import LibraryStore
from lumirss.storage import Database


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture()
def store_env(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    store = AgentStore(db)
    library = LibraryStore(db)
    return {"db": db, "store": store, "library": library}


async def _make_pending(store_env, args=None):
    store = store_env["store"]
    thread = await store.create_thread()
    approval = await store.create_approval(
        thread["id"], "call-1", "save_bookmark",
        args or {"url": "https://example.com/a", "title": "a"},
    )
    return thread["id"], approval["approvalId"]


def test_duplicate_approve_executes_exactly_once(store_env):
    async def scenario():
        thread_id, approval_id = await _make_pending(store_env)
        store = store_env["store"]

        async def claim():
            try:
                return await store.take_approval(thread_id, approval_id)
            except ApprovalInvalid as exc:
                return exc

        first, second = await asyncio.gather(claim(), claim())
        kinds = [type(result).__name__ for result in (first, second)]
        assert kinds.count("dict") == 1, "exactly one claim wins"
        assert kinds.count("ApprovalInvalid") == 1
        # The row is terminal — no third claim.
        with pytest.raises(ApprovalInvalid):
            await store.take_approval(thread_id, approval_id)
        return thread_id

    run(scenario())


def test_approve_executes_row_args_not_message_log(store_env):
    """The executed args come from the approval ROW — the payload the
    user saw. Message-log tampering cannot change what executes."""
    async def scenario():
        row_args = {"url": "https://example.com/real", "title": "real"}
        thread_id, approval_id = await _make_pending(store_env, row_args)
        store = store_env["store"]
        # Simulate the suspended-turn log (approval-role message), then
        # tamper with it — the old code re-derived the expected hash from
        # this log, tautologically; the new take ignores it entirely.
        await store.append_message(
            thread_id,
            role="approval",
            content={"approvalId": approval_id, "tool": "save_bookmark",
                     "args": {"url": "TAMPERED", "title": "TAMPERED"},
                     "callId": "call-1"},
        )
        taken = await store.take_approval(thread_id, approval_id)
        assert taken["args"] == row_args
        assert args_hash(taken["tool"], taken["args"]) == args_hash(
            "save_bookmark", row_args
        )

    run(scenario())


def test_cross_thread_approval_refused(store_env):
    async def scenario():
        thread_a, approval_a = await _make_pending(store_env)
        store = store_env["store"]
        thread_b = await store.create_thread()
        with pytest.raises(ApprovalInvalid):
            await store.take_approval(thread_b["id"], approval_a)
        _ = thread_a

    run(scenario())


def test_expired_approval_marks_expired_and_refuses(store_env, monkeypatch):
    async def scenario():
        thread_id, approval_id = await _make_pending(store_env)
        store = store_env["store"]
        # expire_stale (wired on access) catches the stale pending row.
        await store._db.execute(
            "UPDATE agent_approvals SET created_at = '2020-01-01T00:00:00+00:00' WHERE id = ?",
            (approval_id,),
        )
        assert await store.expire_stale(thread_id) == 1
        with pytest.raises(ApprovalInvalid):
            await store.take_approval(thread_id, approval_id)
        # An in-TTL take that loses the race against the clock still
        # flips the row to expired.
        thread2, approval2 = await _make_pending(store_env)
        await store._db.execute(
            "UPDATE agent_approvals SET created_at = '2020-01-01T00:00:00+00:00' WHERE id = ?",
            (approval2,),
        )
        with pytest.raises(ApprovalInvalid):
            await store.take_approval(thread2, approval2)

    run(scenario())


def test_restart_sweep_finalizes_orphaned_run(store_env):
    """A run marker that survives into a fresh process becomes an
    honest ``interrupted`` assistant message — the UI stops polling."""
    async def scenario():
        store = store_env["store"]
        thread = await store.create_thread()
        await store.mark_run_processing(thread["id"])
        assert await store.is_running(thread["id"]) is True
        await store.append_message(
            thread["id"], role="user", content={"text": "中途重启"}
        )
        # Age the marker behind the (new) process start: it belongs to
        # the PREVIOUS process — exactly the restart signature.
        from lumirss.agent_store import _PROCESS_START, _RUN_KEY_PREFIX

        await store._db.execute(
            "UPDATE lumi_settings SET value = '2020-01-01T00:00:00+00:00' WHERE key = ?",
            (_RUN_KEY_PREFIX + thread["id"],),
        )
        assert _PROCESS_START > "2020-01-01"

        # Simulate a restart: a brand-new AgentStore over the same DB.
        fresh = AgentStore(store_env["db"])
        await fresh.list_threads()  # access triggers the one-shot sweep
        assert await fresh.is_running(thread["id"]) is False
        messages = await fresh.messages_after(thread["id"], 0)
        last = messages[-1]
        assert last["role"] == "assistant"
        assert INTERRUPTED_TEXT in last["content"]["text"]
        assert last["content"].get("interrupted") is True

    run(scenario())


def test_sweep_never_touches_live_runs_of_this_process(store_env):
    """A run marker created by the CURRENT process (turn in flight) is
    not an orphan — history reads during the turn must not 'interrupt'
    it (regression for the sweep-vs-live-run race)."""
    async def scenario():
        store = store_env["store"]
        thread = await store.create_thread()
        await store.mark_run_processing(thread["id"])
        # History read mid-turn triggers ensure_swept:
        messages = await store.messages_after(thread["id"], 0)
        assert messages == []
        assert await store.is_running(thread["id"]) is True
        await store.clear_run(thread["id"])

    run(scenario())


def test_run_markers_lifecycle(store_env):
    async def scenario():
        store = store_env["store"]
        thread = await store.create_thread()
        assert await store.is_running(thread["id"]) is False
        await store.mark_run_processing(thread["id"])
        assert await store.active_run_thread_ids() == [thread["id"]]
        await store.clear_run(thread["id"])
        assert await store.active_run_thread_ids() == []

    run(scenario())


def test_concurrent_appends_get_distinct_seq(store_env):
    """Per-thread serialization of MAX(seq)+1: 20 racing appends produce
    seq 1..20 exactly once each (no duplicate/lost order)."""
    async def scenario():
        store = store_env["store"]
        thread = await store.create_thread()

        async def append(index):
            return await store.append_message(
                thread["id"], role="user", content={"text": f"m{index}"}
            )

        rows = await asyncio.gather(*(append(i) for i in range(20)))
        seqs = sorted(row["seq"] for row in rows)
        assert seqs == list(range(1, 21))

    run(scenario())
