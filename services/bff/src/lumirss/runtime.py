"""ARCH-08 runtime ownership primitives: process-level scheduler slots
and SQLite-backed period leases.

LumiRSS is deliberately a single-binary SQLite deployment (no Redis, no
message broker), so both ownership layers live inside the process and
the per-user Lumi database:

1. ``SchedulerRegistry`` — the lifespan owns one background task per
   slot name (search sync, obsidian scan, digest / IMAP / GPT-digest /
   RAG loops). A repeated startup in the same process (tests re-entering
   the lifespan, a reload handoff that never reached shutdown, an
   accidental double ``uvicorn`` factory call) used to overwrite the
   ``app.state`` task slots and orphan the still-running previous loops:
   shutdown cancelled only the newest task, so duplicates accumulated.
   The registry makes ``start`` idempotent — a slot already owned by a
   live task returns that task instead of spawning a second loop — and
   makes shutdown deterministic (cancel → bounded await → report the
   tasks that refused to stop).

2. ``RuntimeLeases`` — cross-process exclusive window leases in the
   user's own SQLite file. The digest schedulers gate each send/generate
   on persisted state (``last_sent_at`` hour equality; issue-key
   existence), which is TOCTOU-racy across processes: two processes (a
   crashed-then-restarted deployment on the same data dir, or an
   accidental second instance) can both pass the check before either
   writes its result and double-send / double-generate. A lease row is
   taken for the exact window before the side effect, so only one owner
   runs per window: live leases are never stolen, expired leases are
   takeable (crash recovery), and release is owner-checked.
"""

import asyncio
import logging
import os
import sqlite3
import uuid
from collections.abc import Callable
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now as _utc_now

_logger = logging.getLogger("lumirss.runtime")


class SchedulerRegistry:
    """Process-level single-owner registry for lifespan background tasks.

    ``start(name, factory)`` returns the live task already owning the
    slot when one exists (idempotent), and only calls ``factory()``
    otherwise. ``stop_all`` implements the ARCH-08 shutdown contract:
    cancel every slot → await with a hard timeout → return the names of
    tasks that did not finish in time so the caller can report them.
    """

    def __init__(self) -> None:
        self._slots: dict[str, asyncio.Task] = {}

    def start(self, name: str, factory: Callable[[], asyncio.Task]) -> asyncio.Task:
        """Own ``name`` by exactly one live task in this process.

        A done task (crashed loop, completed one-shot) releases its slot
        implicitly; a live task means a previous startup in this process
        never shut down — returning it is the honest single-owner
        behavior instead of orphaning a duplicate.
        """
        existing = self._slots.get(name)
        if existing is not None and not existing.done():
            return existing
        task = factory()
        self._slots[name] = task
        return task

    def owned_names(self) -> list[str]:
        """Slot names currently held by a live task (diagnostics/tests)."""
        return sorted(
            name
            for name, task in self._slots.items()
            if not task.done()
        )

    async def stop_all(self, *, timeout: float = 10.0) -> list[str]:
        """Deterministic stop: cancel → bounded await → report.

        Returns the slot names still running after ``timeout`` seconds.
        Idempotent: the registry is cleared up front, so a shutdown that
        follows an earlier shutdown (or a lifespan re-entered while
        already stopping) is a no-op. Tasks belonging to a foreign event
        loop (a lifespan whose loop died without shutdown) are cancelled
        but not awaited — awaiting them would raise cross-loop errors.
        """
        slots = list(self._slots.items())
        self._slots.clear()
        if not slots:
            return []
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        awaitable: list[tuple[str, asyncio.Task]] = []
        for name, task in slots:
            try:
                task.cancel()
            except RuntimeError:
                # The task's event loop is already closed (a lifespan whose
                # loop died without shutdown) — there is nothing left to
                # cancel or await; releasing the slot is the honest stop.
                _logger.warning(
                    "scheduler slot %s belongs to a closed event loop; "
                    "slot released without cancellation",
                    name,
                )
                continue
            if loop is not None and task.get_loop() is loop:
                awaitable.append((name, task))
            else:
                _logger.warning(
                    "scheduler slot %s belongs to a foreign event loop; "
                    "cancelled without await",
                    name,
                )
        if not awaitable:
            return []
        done, pending = await asyncio.wait(
            [task for _, task in awaitable], timeout=timeout
        )
        done_ids = {id(task) for task in done}
        stragglers = [
            name for name, task in awaitable if id(task) not in done_ids
        ]
        if stragglers:
            _logger.warning(
                "background tasks did not stop within %.1fs: %s",
                timeout,
                ", ".join(sorted(stragglers)),
            )
        return stragglers


# Lifespan-level singleton: one process owns exactly one set of
# background loops no matter how often the lifespan (re)starts.
SCHEDULERS = SchedulerRegistry()


_DEFAULT_LEASE_TTL_SECONDS = 900.0


class RuntimeLeases:
    """Exclusive window leases persisted in the caller's SQLite file.

    One row per ``scope`` (e.g. ``digest:2026-09-28T08`` or
    ``gpt-digest:3:2026-09-28``): the owner that acquired it holds the
    window until ``release`` or until ``expires_at`` passes. The
    acquire path is process-safe without SELECT/INSERT TOCTOU: the row
    is claimed by INSERT (PRIMARY KEY arbitrates concurrent claimants)
    and an expired row is taken over by a conditional UPDATE whose
    WHERE-clause is evaluated atomically by SQLite. Every acquire also
    sweeps expired rows so the table stays bounded (one row per window
    until it expires).

    ``now_fn`` is injectable for deterministic tests; production uses
    :func:`lumirss.util.utc_now` (fixed-format ISO UTC, so string
    comparison is ordering-correct).
    """

    def __init__(
        self,
        db: Database,
        *,
        ttl_seconds: float = _DEFAULT_LEASE_TTL_SECONDS,
        owner: str | None = None,
        now_fn: Callable[[], str] | None = None,
    ) -> None:
        self._db = db
        self._ttl = ttl_seconds
        self._owner = owner or f"proc-{os.getpid()}-{uuid.uuid4().hex}"
        self._now_fn = now_fn or _utc_now

    @property
    def owner(self) -> str:
        return self._owner

    async def acquire(self, scope: str) -> bool:
        """Claim ``scope``. True exactly when this owner holds it.

        Live leases are never stolen by ANOTHER owner; the holder itself
        may re-acquire (a fresh claim extension, same exclusivity), and a
        lease whose ``expires_at`` has passed is takeable by anyone (a
        crashed owner cannot wedge the window forever). The expiry sweep
        keeps the table bounded.
        """
        await self._db.migrate()
        from lumirss.db_tx import transaction

        def _acquire(connection: sqlite3.Connection) -> bool:
            now = self._now_fn()
            expires = _bump(now, self._ttl)
            connection.execute(
                "DELETE FROM runtime_leases WHERE expires_at <= ?",
                (now,),
            )
            try:
                connection.execute(
                    "INSERT INTO runtime_leases "
                    "(scope, owner, expires_at, acquired_at) "
                    "VALUES (?, ?, ?, ?)",
                    (scope, self._owner, expires, now),
                )
                return True
            except sqlite3.IntegrityError:
                pass
            cursor = connection.execute(
                "UPDATE runtime_leases "
                "SET owner = ?, expires_at = ?, acquired_at = ? "
                "WHERE scope = ? AND (expires_at <= ? OR owner = ?)",
                (self._owner, expires, now, scope, now, self._owner),
            )
            return cursor.rowcount == 1

        return await transaction(self._db, _acquire)

    async def release(self, scope: str) -> None:
        """Give up ``scope`` — only if this owner still holds it.

        An owner-checked delete can never free a window taken over by a
        newer owner (its lease simply survives until expiry).
        """
        await self._db.migrate()
        from lumirss.db_tx import transaction

        def _release(connection: sqlite3.Connection) -> None:
            connection.execute(
                "DELETE FROM runtime_leases WHERE scope = ? AND owner = ?",
                (scope, self._owner),
            )

        await transaction(self._db, _release)

    async def inspect(self, scope: str) -> dict[str, Any] | None:
        """The raw lease row (diagnostics/tests), or None when unheld."""
        row = await self._db.fetch_one(
            "SELECT scope, owner, expires_at, acquired_at "
            "FROM runtime_leases WHERE scope = ?",
            (scope,),
        )
        if row is None:
            return None
        return {
            "scope": str(row["scope"]),
            "owner": str(row["owner"]),
            "expires_at": str(row["expires_at"]),
            "acquired_at": str(row["acquired_at"]),
        }


def _bump(iso_now: str, ttl_seconds: float) -> str:
    """``iso_now + ttl`` in the same persisted ISO-UTC format."""
    from datetime import datetime, timedelta

    moment = datetime.fromisoformat(iso_now)
    return (moment + timedelta(seconds=ttl_seconds)).isoformat(
        timespec="seconds"
    )
