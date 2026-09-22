"""Legacy single-user → owner account migration (O148, idempotent).

LumiRSS shipped single-user: one SQLite file (LUMIRSS_DB_PATH) holding
both auth rows and every business table. 0067 introduces invite-only
accounts where the control database keeps identity only and each user's
business data lives in ``<data_dir>/users/<uid>/lumi.sqlite``.

This module runs once at startup (before the app serves) and converges
any pre-0067 layout onto the new one:

1. control database has no users AND the legacy file still carries a
   pre-0067 schema → create the ``owner`` account and physically move
   the legacy file to the owner's user database (rename = zero-copy,
   content and rowid preserving; WAL/SHM sidecars move with it);
2. a fresh control database is created in its place and migrated
   (empty business tables are harmless — they are never queried);
3. the owner's FreshRSS binding is seeded from the environment
   credentials when present (the operator's own account), and the API
   password moves into the owner's secrets file;
4. machine-channel tokens (feed / ingest bearer hashes) are indexed in
   the control ``token_owner_index`` so those channels keep resolving
   to the owner.

Re-running is a no-op (users already exist). Operators take the pre-
migration backup (``./lumirss backup``); this module never deletes the
legacy content — the rename either fully happens or not at all.
"""

import logging
import secrets
import shutil
import sqlite3
from pathlib import Path

from lumirss.config import FreshRSSSettings, LumiSettings
from lumirss.storage import Database

_logger = logging.getLogger("lumirss.accounts")


def _schema_is_pre_multitone(path: Path) -> bool:
    """True when the file exists and has NOT run the 0067 migration."""
    if not path.exists():
        return False
    try:
        connection = sqlite3.connect(str(path), timeout=5.0)
        try:
            row = connection.execute("SELECT COUNT(*) FROM schema_migrations WHERE version = 67").fetchone()
            return int(row[0]) == 0
        finally:
            connection.close()
    except sqlite3.Error:
        return False


def _legacy_password_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        connection = sqlite3.connect(str(path), timeout=5.0)
        try:
            row = connection.execute("SELECT password_hash FROM auth_password WHERE id = 1").fetchone()
            return str(row[0]) if row else None
        finally:
            connection.close()
    except sqlite3.Error:
        return None


def _index_saved_search_tokens(connection: sqlite3.Connection, found: list[tuple[str, str]]) -> None:
    for row in connection.execute("SELECT feed_secret FROM saved_searches WHERE feed_secret IS NOT NULL AND feed_secret != ''").fetchall():
        found.append((str(row[0]), "saved_searches"))


def _index_mail_bridge_tokens(connection: sqlite3.Connection, found: list[tuple[str, str]]) -> None:
    for row in connection.execute("SELECT secret FROM mail_bridge_lists WHERE secret IS NOT NULL AND secret != ''").fetchall():
        found.append((str(row[0]), "mail_bridge_lists"))


def _index_inbox_tokens(connection: sqlite3.Connection, found: list[tuple[str, str]]) -> None:
    for row in connection.execute("SELECT secret FROM inbox_sources WHERE secret IS NOT NULL AND secret != ''").fetchall():
        found.append((str(row[0]), "inbox_sources"))


def _index_api_source_tokens(connection: sqlite3.Connection, found: list[tuple[str, str]]) -> None:
    for row in connection.execute("SELECT secret FROM api_sources WHERE secret IS NOT NULL AND secret != ''").fetchall():
        found.append((str(row[0]), "api_sources"))


def _index_machine_tokens(user_db_path: Path, owner_id: str, control: Database) -> None:
    """Copy (token-hash, owner) pairs into the control index (idempotent).

    One explicit literal query per source table — the set of columns is
    fixed by the historical schema, never user-influenced. Hash-only
    rows are the normal case (0066 backfill); plaintext legacy rows are
    indexed as-is (verify paths stay compatible) until the startup
    backfill hashes them.
    """
    if not user_db_path.exists():
        return
    indexers = (
        _index_saved_search_tokens,
        _index_mail_bridge_tokens,
        _index_inbox_tokens,
        _index_api_source_tokens,
    )
    found: list[tuple[str, str]] = []
    try:
        connection = sqlite3.connect(str(user_db_path), timeout=5.0)
        try:
            for index_missing_table in indexers:
                try:
                    index_missing_table(connection, found)
                except sqlite3.Error:
                    continue  # table absent in very old schemas
        finally:
            connection.close()
        for token_hash, purpose in found:
            control.exec_sync("INSERT OR IGNORE INTO token_owner_index (token_hash, user_id, purpose, created_at) VALUES (?, ?, ?, 0)", (token_hash, owner_id, purpose))
    except sqlite3.Error:
        _logger.exception("machine token indexing failed (affected feeds may need re-issue)")


async def ensure_owner_migration(db: Database, control_secrets) -> str | None:
    """Converge the legacy layout; returns the owner user id.

    ``db`` is the CONTROL database handle and ``control_secrets`` the
    control-level SecretsStore. Called from lifespan before any request
    is served.
    """
    from lumirss.accounts_store import AccountsStore, hash_password
    from lumirss.user_scope import user_context

    await db.migrate()
    accounts = AccountsStore(db)
    for row in await accounts.list_users(limit=500):
        if row.get("role") == "owner":
            return str(row["id"])

    settings = LumiSettings()
    legacy_path = Path(settings.LUMIRSS_DB_PATH)
    users_root = legacy_path.parent / "users"

    legacy_hash = _legacy_password_hash(legacy_path)
    if legacy_hash is None:
        # No usable legacy password: install an unguessable one. The real
        # password is set through the normal set-password flow — the
        # migration never invents a password anybody knows.
        legacy_hash = hash_password(secrets.token_urlsafe(32))
    owner = await accounts.create_user(
        username="owner",
        password_hash=legacy_hash,
        role="owner",
        display_name="Owner",
    )
    owner_id = str(owner["id"])

    if _schema_is_pre_multitone(legacy_path):
        target_dir = users_root / owner_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "lumi.sqlite"
        for sidecar in ("-wal", "-shm"):
            source_sidecar = Path(str(legacy_path) + sidecar)
            if source_sidecar.exists():
                shutil.move(str(source_sidecar), str(target) + sidecar)
        shutil.move(str(legacy_path), str(target))
        _logger.info("owner migration: legacy database moved to %s", target)
        _index_machine_tokens(target, owner_id, db)

    # Seed the owner's FreshRSS binding from the deployment env — the
    # operator's own account. This is the ONLY env fallback and it is
    # granted once, at migration time; every other user binds through
    # the invitation pool (O154). Fresh installs without env credentials
    # simply stay unbound (honest empty state until the operator adds a
    # source account).
    try:
        freshrss = FreshRSSSettings()
    except Exception:  # noqa: BLE001 — unconfigured installs bind later
        freshrss = None
    if freshrss is not None:
        with user_context(owner_id):
            await db.execute("INSERT OR REPLACE INTO freshrss_binding (id, base_url, username, public_url, bound_at, source) VALUES (1, ?, ?, ?, 0, 'env')", (freshrss.FRESHRSS_BASE_URL, freshrss.FRESHRSS_USERNAME, freshrss.FRESHRSS_PUBLIC_URL))
            control_secrets.set("freshrss_api_password", freshrss.FRESHRSS_API_PASSWORD.get_secret_value())

    await accounts.audit(actor="system", action="owner_migration", object_type="user", object_id=owner_id)
    return owner_id
