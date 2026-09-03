"""Tests for the Lumi SQLite foundation (0015 Gate 1).

Every test uses a temp database file (tmp_path) — the repository-wide
rule that tests never touch the real Lumi/FreshRSS data applies here too.

The suite has no pytest-asyncio dependency: async storage calls are driven
with ``asyncio.run`` inside plain sync tests.
"""

import asyncio
import sqlite3

import pytest

from lumirss.migrations import list_migrations, schema_version
from lumirss.storage import Database, DatabaseError


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "lumi.sqlite")


def run(coroutine):
    return asyncio.run(coroutine)


def test_fresh_database_migrates_all_migrations(db):
    applied = run(db.migrate())

    assert applied == [version for version, _ in list_migrations()]
    assert schema_version(db) == list_migrations()[-1][0]


def test_restart_is_idempotent(db):
    run(db.migrate())
    applied_again = run(db.migrate())

    assert applied_again == []
    assert schema_version(db) == list_migrations()[-1][0]


def test_migration_versions_are_contiguous_and_deterministic():
    migrations = list_migrations()
    versions = [version for version, _ in migrations]

    assert versions == sorted(versions)
    assert len(set(versions)) == len(versions)
    assert versions[0] == 1
    assert versions == list(range(1, len(versions) + 1))


def test_insert_and_read_persist_across_connections(db):
    run(db.migrate())
    run(
        db.execute(
            "INSERT INTO lumi_settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("ai.model", "deepseek-chat", "2026-09-02T00:00:00+00:00"),
        )
    )
    row = run(
        db.fetch_one(
            "SELECT value FROM lumi_settings WHERE key = ?", ("ai.model",)
        )
    )

    assert row is not None
    assert row["value"] == "deepseek-chat"


def test_data_survives_database_reopen(tmp_path):
    path = tmp_path / "lumi.sqlite"
    first = Database(path)
    run(first.migrate())
    run(
        first.execute(
            "INSERT INTO lumi_settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("ai.base_url", "https://api.example.com/v1", "2026-09-02T00:00:00+00:00"),
        )
    )

    reopened = Database(path)
    row = run(
        reopened.fetch_one(
            "SELECT value FROM lumi_settings WHERE key = ?", ("ai.base_url",)
        )
    )

    assert row is not None
    assert row["value"] == "https://api.example.com/v1"


def test_unique_cache_identity_constraint(db):
    run(db.migrate())
    base = (
        "INSERT INTO ai_summaries (entry_ref, content_hash, provider, model, "
        "prompt_version, language, status, summary_text, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    args = (
        "ref-1", "hash-1", "openai_compatible", "model-a",
        "summary-v1", "zh-CN", "success", "摘要",
        "2026-09-02T00:00:00+00:00", "2026-09-02T00:00:00+00:00",
    )
    run(db.execute(base, args))

    with pytest.raises(DatabaseError):
        run(db.execute(base, args))


def test_invalid_status_rejected_by_check_constraint(db):
    run(db.migrate())
    with pytest.raises(DatabaseError):
        run(
            db.execute(
                "INSERT INTO ai_summaries (entry_ref, content_hash, provider, model, "
                "prompt_version, language, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "ref-1", "hash-1", "openai_compatible", "model-a",
                    "summary-v1", "zh-CN", "bogus",
                    "2026-09-02T00:00:00+00:00", "2026-09-02T00:00:00+00:00",
                ),
            )
        )


def test_failed_migration_is_rolled_back_and_not_recorded(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    expected_version = list_migrations()[-1][0]
    assert schema_version(db) == expected_version

    # Inject a broken migration file, then verify it raises and nothing
    # was marked applied.
    import lumirss.migrations as migrations

    broken = migrations.MIGRATIONS_DIR / "9999_broken.sql"
    broken.write_text("CREATE TABLE definitely_broken (id INTEGER;\n", encoding="utf-8")
    try:
        # A fresh Database instance on the same file re-scans migrations
        # (an already-migrated instance skips by design).
        reopened = Database(tmp_path / "lumi.sqlite")
        with pytest.raises(DatabaseError):
            run(reopened.migrate())
        assert schema_version(db) == expected_version
        # The partially parsed statement must not have left a table behind.
        connection = sqlite3.connect(str(db.path))
        try:
            names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        finally:
            connection.close()
        assert "definitely_broken" not in names
    finally:
        broken.unlink()