"""ARCH-08 runtime lifecycle behavior: single-owner schedulers, period
leases, deterministic shutdown, and the startup ordering contract.

Everything here is behavioral, on the REAL lifespan / real SQLite files
(two ``Database`` handles on one file stand in for two processes — the
repo is deliberately single-binary SQLite, so the tests must prove the
ownership semantics WITHOUT any new infrastructure).
"""

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from lumirss.runtime import (
    SCHEDULERS,
    RuntimeLeases,
    SchedulerRegistry,
)
from lumirss.storage import Database


def run(coroutine):
    return asyncio.run(coroutine)


# ---- deterministic clock stubs ----------------------------------------------


class _LeaseClock:
    """Injectable ``now_fn`` for RuntimeLeases (ISO-UTC strings)."""

    def __init__(self, start: datetime) -> None:
        self._moment = start

    def advance(self, seconds: float) -> None:
        self._moment = self._moment + timedelta(seconds=seconds)

    def __call__(self) -> str:
        return self._moment.isoformat(timespec="seconds")


def _frozen_wall(moment: datetime):
    """DigestScheduler/GptDigestScheduler ``clock`` (tz-aware datetime)."""
    return lambda _tz: moment


def _tmp_db(tmp_path, name: str = "lumi.sqlite") -> Database:
    """Sync-context helper (NEVER call from inside a running loop)."""
    db = Database(tmp_path / name)
    run(db.migrate())
    return db


async def _tmp_db_async(tmp_path, name: str = "lumi.sqlite") -> Database:
    db = Database(tmp_path / name)
    await db.migrate()
    return db


# ---- 1. process-level single-owner registry ---------------------------------


def test_registry_repeated_start_is_idempotent_until_stopped():
    """Repeated startup in one process: the live task is returned as-is —
    the factory runs exactly once per (start → stop → start) cycle."""

    async def scenario():
        registry = SchedulerRegistry()
        created: list[asyncio.Task] = []

        def factory() -> asyncio.Task:
            task = asyncio.create_task(asyncio.sleep(3600))
            created.append(task)
            return task

        first = registry.start("digest_scheduler", factory)
        second = registry.start("digest_scheduler", factory)
        assert first is second, "second startup must reuse the live task"
        assert len(created) == 1

        assert await registry.stop_all(timeout=1.0) == []
        assert first.cancelled()

        third = registry.start("digest_scheduler", factory)
        assert third is not first, "clean shutdown must allow a restart"
        assert len(created) == 2
        assert await registry.stop_all(timeout=1.0) == []

    run(scenario())


def test_registry_stop_all_reports_stragglers_within_timeout():
    """Shutdown contract: cancel → bounded await → report the task that
    refuses to die, while well-behaved tasks stop cleanly. The bound is
    the ``timeout`` parameter, not a sleep."""

    async def scenario():
        registry = SchedulerRegistry()
        good_released = asyncio.Event()

        async def good() -> None:
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.sleep(3600)
            good_released.set()

        swallow_count = {"n": 0}

        async def stubborn() -> None:
            while True:
                try:
                    await asyncio.sleep(3600)
                except asyncio.CancelledError:
                    swallow_count["n"] += 1
                    if swallow_count["n"] > 1:
                        raise

        registry.start("good", lambda: asyncio.create_task(good()))
        stubborn_task = registry.start(
            "stubborn", lambda: asyncio.create_task(stubborn())
        )
        # one scheduler yield: both tasks reach their await point, so the
        # cancellation below is delivered INSIDE the coroutines (a task
        # cancelled before its first step dies without running any code).
        await asyncio.sleep(0)

        started = asyncio.get_running_loop().time()
        stragglers = await registry.stop_all(timeout=0.05)
        elapsed = asyncio.get_running_loop().time() - started

        assert stragglers == ["stubborn"], "the wedged task must be reported"
        assert good_released.is_set(), "well-behaved task stopped cleanly"
        assert elapsed < 5.0, "stop must be bounded by the timeout, not hang"
        assert registry.owned_names() == [], "slots released up front"

        # cleanup: the second cancel makes the stub re-raise and finish
        stubborn_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stubborn_task

    run(scenario())


def test_registry_stop_all_ignores_foreign_loop_tasks():
    """A lifespan whose event loop died without shutdown leaves a task
    bound to another loop; stop_all cancels it but must not await it
    (cross-loop await raises) — the slot is released regardless."""

    loop1 = asyncio.new_event_loop()
    task = loop1.create_task(asyncio.sleep(3600))
    loop1.run_until_complete(asyncio.sleep(0))  # task started, mid-sleep

    registry = SchedulerRegistry()
    registry._slots["orphaned"] = task  # type: ignore[index] — stale slot

    loop2 = asyncio.new_event_loop()
    try:
        stragglers = loop2.run_until_complete(
            registry.stop_all(timeout=0.05)
        )
    finally:
        loop2.close()
    assert stragglers == [], "foreign-loop task is not awaitable"
    assert registry.owned_names() == []

    # the cancel stop_all scheduled still lands in its own loop
    loop1.run_until_complete(asyncio.sleep(0))
    assert task.cancelled()
    loop1.close()


# ---- 2. real lifespan: repeated startup, order, shutdown --------------------


_ALWAYS_ON_SLOTS = (
    ("digest_scheduler_task", "digest_scheduler"),
    ("mail_imap_task", "mail_imap"),
    ("gpt_digest_scheduler_task", "gpt_digest_scheduler"),
    ("rag_idle_task", "rag_idle"),
)


def test_repeated_lifespan_same_process_starts_exactly_one_scheduler_set():
    """ARCH-08 acceptance: repeated startup in one process → exactly one
    scheduler instance per slot; shutdown releases every slot; a later
    restart gets fresh tasks (single worker / restart behavior)."""
    from lumirss.main import lifespan

    async def scenario():
        app_a = SimpleNamespace(state=SimpleNamespace())
        app_b = SimpleNamespace(state=SimpleNamespace())
        async with contextlib.AsyncExitStack() as stack:
            await stack.enter_async_context(lifespan(app_a))
            await stack.enter_async_context(lifespan(app_b))

            for attr, slot in _ALWAYS_ON_SLOTS:
                task_a = getattr(app_a.state, attr)
                task_b = getattr(app_b.state, attr)
                assert isinstance(task_a, asyncio.Task), slot
                assert task_b is task_a, (
                    f"{slot}: second startup must reuse the live task"
                )
                assert not task_a.done(), slot
            # interval defaults/conftest: rag index on, search sync + obsidian off
            assert isinstance(app_a.state.rag_index_task, asyncio.Task)
            assert app_a.state.search_sync_task is None
            assert app_a.state.obsidian_scan_task is None
            assert sorted(SCHEDULERS.owned_names()) == sorted(
                [slot for _, slot in _ALWAYS_ON_SLOTS] + ["rag_index"]
            )

            first_set = [getattr(app_a.state, attr) for attr, _ in _ALWAYS_ON_SLOTS]

        # shutdown: every slot released, every task actually stopped
        assert SCHEDULERS.owned_names() == []
        for task in first_set:
            assert task.cancelled()

        # restart after clean shutdown → NEW tasks, not the cancelled ones
        app_c = SimpleNamespace(state=SimpleNamespace())
        async with lifespan(app_c):
            for attr, _ in _ALWAYS_ON_SLOTS:
                assert getattr(app_c.state, attr) not in first_set
                assert not getattr(app_c.state, attr).done()
            assert len(SCHEDULERS.owned_names()) == 5
        assert SCHEDULERS.owned_names() == []

    run(scenario())


def test_lifespan_startup_completes_migrations_before_schedulers_start():
    """Ordering contract: at ready (yield) the control database is fully
    migrated (incl. 0140) and the owner exists — schedulers only start
    on top of a migrated, identity-complete control database."""

    async def scenario():
        from lumirss.main import lifespan
        from lumirss.migrations import list_migrations

        app = SimpleNamespace(state=SimpleNamespace())
        async with lifespan(app):
            max_known = max(version for version, _ in list_migrations())
            row = await app.state.control_db.fetch_one(
                "SELECT COALESCE(MAX(version), 0) AS v FROM schema_migrations"
            )
            assert int(row["v"]) == max_known, (
                "ready must come after all migrations"
            )
            assert app.state.owner_id, "owner identity exists before ready"
            for _, slot in _ALWAYS_ON_SLOTS:
                assert slot in SCHEDULERS.owned_names(), (
                    f"{slot} started only after migration"
                )
        assert SCHEDULERS.owned_names() == []

    run(scenario())


def test_lifespan_startup_failure_never_starts_schedulers(
    monkeypatch: pytest.MonkeyPatch,
):
    """If migrations fail, startup aborts BEFORE any scheduler task is
    spawned — the registry stays empty (no orphaned loops behind a dead
    lifespan)."""
    import lumirss.migrations as migrations_module
    from lumirss.main import lifespan
    from lumirss.storage import DatabaseError

    def _boom(_db):
        raise DatabaseError("injected migration failure")

    monkeypatch.setattr(migrations_module, "apply_migrations", _boom)

    async def scenario():
        app = SimpleNamespace(state=SimpleNamespace())
        with pytest.raises(DatabaseError):
            async with lifespan(app):
                raise AssertionError("ready must not be reached")  # pragma: no cover
        assert SCHEDULERS.owned_names() == []
        await app.state.http_client.aclose()

    run(scenario())


# ---- 3. period leases (RuntimeLeases, cross-process via two handles) --------


def test_lease_live_not_stolen_expired_takeable_release_owner_checked(tmp_path):
    db_a = _tmp_db(tmp_path, "a.sqlite")
    db_b = Database(tmp_path / "a.sqlite")  # second handle == second process
    clock_a = _LeaseClock(datetime(2026, 9, 28, 8, 0, tzinfo=UTC))
    clock_b = _LeaseClock(datetime(2026, 9, 28, 8, 0, tzinfo=UTC))
    owner_a = RuntimeLeases(
        db_a, ttl_seconds=60, owner="proc-a", now_fn=clock_a
    )
    owner_b = RuntimeLeases(
        db_b, ttl_seconds=60, owner="proc-b", now_fn=clock_b
    )
    scope = "digest:2026-09-28T08"

    # live lease: second process cannot take it
    assert run(owner_a.acquire(scope)) is True
    assert run(owner_b.acquire(scope)) is False
    held = run(owner_b.inspect(scope))
    assert held is not None and held["owner"] == "proc-a"

    # re-acquire by the same owner is a fresh claim extension, still exclusive
    assert run(owner_a.acquire(scope)) is True
    assert run(owner_b.acquire(scope)) is False

    # owner-checked release: b can never free a's window
    run(owner_b.release(scope))
    assert run(owner_b.inspect(scope)) is not None

    # expired lease is takeable (crash recovery), then live again for b
    clock_b.advance(61)
    assert run(owner_b.acquire(scope)) is True
    assert run(owner_a.acquire(scope)) is False

    # b releases honestly → window free again
    run(owner_b.release(scope))
    assert run(owner_b.inspect(scope)) is None
    assert run(owner_a.acquire(scope)) is True
    run(owner_a.release(scope))


def test_lease_table_stays_bounded_expired_rows_swept(tmp_path):
    db = _tmp_db(tmp_path, "bounded.sqlite")
    clock = _LeaseClock(datetime(2026, 9, 28, 8, 0, tzinfo=UTC))
    leases = RuntimeLeases(db, ttl_seconds=60, owner="p", now_fn=clock)

    for hour in range(3):
        assert run(leases.acquire(f"digest:2026-09-28T0{hour}")) is True

    clock.advance(61)  # all three expired now
    assert run(leases.acquire("digest:2026-09-28T08")) is True

    async def count_rows() -> int:
        row = await db.fetch_one("SELECT COUNT(*) AS n FROM runtime_leases")
        return int(row["n"])

    assert run(count_rows()) == 1, "expired rows are swept on acquire"


