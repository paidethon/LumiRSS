"""Lightweight versioned SQLite migrations (0015).

Design:

- migration files live in ``lumirss/migrations/`` and are named
  ``NNNN_description.sql`` (lexicographic order == version order);
- ``schema_migrations(version, applied_at)`` records what ran;
- each pending migration runs inside its own BEGIN IMMEDIATE transaction
  and is recorded only after the whole file succeeded — a failure rolls
  back and raises, so a migration is never silently marked complete;
- re-running on an unchanged database is a no-op (idempotent restart).

Deliberately NOT Alembic/SQLAlchemy: the schema is small and owned by
Lumi; this runner is ~100 lines and has no new dependencies.
"""

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from lumirss.storage import Database, DatabaseError

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

_MIGRATION_NAME = re.compile(r"^(?P<version>\d{4})_(?P<name>[A-Za-z0-9_-]+)\.sql$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def list_migrations() -> list[tuple[int, Path]]:
    """Deterministically ordered (version, path) pairs, validated."""
    entries: dict[int, Path] = {}
    for path in MIGRATIONS_DIR.glob("*.sql"):
        match = _MIGRATION_NAME.match(path.name)
        if match is None:
            raise DatabaseError(
                f"Migration file '{path.name}' does not match NNNN_name.sql."
            )
        version = int(match.group("version"))
        if version in entries:
            raise DatabaseError(f"Duplicate migration version {version:04d}.")
        entries[version] = path
    return sorted(entries.items())


def _statements(sql: str) -> list[str]:
    """Split a migration file into complete statements (stdlib parser).

    Line comments (``--``) are stripped; blank lines ignored.
    """
    statements: list[str] = []
    buffer = ""
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buffer += line + "\n"
        if sqlite3.complete_statement(buffer.strip()):
            statements.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        raise DatabaseError("Migration file ends with an incomplete SQL statement.")
    return statements


def apply_migrations(database: Database) -> list[int]:
    """Apply every pending migration; return newly applied versions.

    Sync function (runs inside ``asyncio.to_thread`` via Database.migrate).
    """
    connection = database._connect()  # noqa: SLF001 — same module family
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, "
            "applied_at TEXT NOT NULL)"
        )
        connection.commit()
        applied = {
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations")
        }
        newly_applied: list[int] = []
        for version, path in list_migrations():
            if version in applied:
                continue
            sql = path.read_text(encoding="utf-8")
            connection.execute("BEGIN IMMEDIATE")
            try:
                for statement in _statements(sql):
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (version, _utc_now()),
                )
                connection.commit()
            except Exception as exc:
                connection.rollback()
                raise DatabaseError(
                    f"Migration {path.name} failed and was rolled back."
                ) from exc
            newly_applied.append(version)
        return newly_applied
    finally:
        connection.close()


def schema_version(database: Database) -> int:
    """Current schema version, or 0 when nothing has been applied."""
    with database._connect() as connection:  # noqa: SLF001
        row = connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()
    return int(row[0])
