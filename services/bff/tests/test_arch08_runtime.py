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

from lumirss.runtime import RuntimeLeases, SchedulerRegistry
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


