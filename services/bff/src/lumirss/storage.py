"""Lumi SQLite storage foundation (0015).

Small, explicit, stdlib-only persistence layer:

- one configurable database file (LUMIRSS_DB_PATH);
- a connection per operation (no global cursor, no long-lived connection);
- PRAGMA foreign_keys / busy_timeout / WAL on every connection;
- sync sqlite3 wrapped in ``asyncio.to_thread`` so async routes never
  block the event loop;
- versioned migrations applied lazily on first storage use, idempotent
  across restarts (see migrations.py).

This file intentionally does NOT model RSS domain data — FreshRSS remains
the RSS-domain source of truth and lumi.sqlite must never shadow-copy it.
"""

import asyncio
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")


class DatabaseError(Exception):
    """A storage-level failure (connection, migration, integrity)."""


class Database:
    """A SQLite database handle for one Lumi state file."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._migrate_lock = asyncio.Lock()
        self._migrated = False

    @property
    def path(self) -> Path:
        return self._path

    def invalidate_migration_cache(self) -> None:
        """Force migrations to re-run lazily after a live restore (0018)."""
        self._migrated = False

    def _connect(self) -> sqlite3.Connection:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(self._path), timeout=5.0)
        except (OSError, sqlite3.Error) as exc:
            raise DatabaseError(f"Could not open Lumi database {self._path}.") from exc
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error as exc:
            connection.close()
            raise DatabaseError("Could not configure Lumi database connection.") from exc
        return connection

    async def _run(self, operation: Callable[..., T], *args: Any) -> T:
        return await asyncio.to_thread(operation, *args)

    async def migrate(self) -> list[int]:
        """Apply pending migrations exactly once (idempotent restart).

        Returns the versions newly applied in this process. Failures roll
        back the failing migration and raise DatabaseError — a migration is
        never silently marked complete.
        """
        async with self._migrate_lock:
            if self._migrated:
                return []
            from lumirss.migrations import apply_migrations

            applied = await self._run(apply_migrations, self)
            self._migrated = True
            return applied

    def _fetch_one(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> sqlite3.Row | None:
        with closing(self._connect()) as connection:
            return connection.execute(sql, params).fetchone()

    def _fetch_all(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> list[sqlite3.Row]:
        with closing(self._connect()) as connection:
            return list(connection.execute(sql, params).fetchall())

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> int | None:
        with closing(self._connect()) as connection:
            cursor = connection.execute(sql, params)
            connection.commit()
            return cursor.lastrowid

    def _execute_many(
        self, sql: str, params: list[tuple[Any, ...]]
    ) -> None:
        with closing(self._connect()) as connection:
            connection.executemany(sql, params)
            connection.commit()

    async def fetch_one(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> sqlite3.Row | None:
        """One row or None. Callers must call migrate() first when the
        statement depends on the current schema."""
        try:
            return await self._run(self._fetch_one, sql, params)
        except sqlite3.Error as exc:
            raise DatabaseError(f"Lumi database query failed: {sql.splitlines()[0].strip()}") from exc

    async def fetch_all(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> list[sqlite3.Row]:
        """All rows. Callers must call migrate() first when the statement
        depends on the current schema."""
        try:
            return await self._run(self._fetch_all, sql, params)
        except sqlite3.Error as exc:
            raise DatabaseError(f"Lumi database query failed: {sql.splitlines()[0].strip()}") from exc

    async def execute(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> int | None:
        """One write statement (committed). Returns lastrowid."""
        try:
            return await self._run(self._execute, sql, params)
        except sqlite3.Error as exc:
            raise DatabaseError(f"Lumi database write failed: {sql.splitlines()[0].strip()}") from exc

    async def execute_many(
        self, sql: str, params: list[tuple[Any, ...]]
    ) -> None:
        """Many write statements in one transaction."""
        try:
            await self._run(self._execute_many, sql, params)
        except sqlite3.Error as exc:
            raise DatabaseError(f"Lumi database write failed: {sql.splitlines()[0].strip()}") from exc
