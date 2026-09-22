"""Per-user data scoping (0067 邀请制多账户) — the isolation seam.

One decision, applied everywhere (任务书 §5.2): 账户控制存储 +
每用户业务数据库. The control database (LUMIRSS_DB_PATH) keeps
identity/sessions/invites/pool/audit (accounts_store). Each user's
business data lives in its own SQLite file under
``<data_dir>/users/<uid>/lumi.sqlite`` plus a per-user ``secrets.json``
and asset root — the original single-user schema and repositories run
unchanged against the user file.

Mechanism: :class:`RoutingDatabase` is stored on ``app.state.db`` where
the historical single-user ``Database`` used to sit. It implements the
same async surface, but every connection resolves to the *current
request's* user database via a ContextVar that the session middleware
sets once per request (and background loops set explicitly). Stores and
routers keep taking ``db: Database`` — they become multi-user without
touching their SQL. Missing identity is a hard error: no anonymous
request can silently land on a default/owner database (O145).

The user id itself is always server-derived (verified session or
verified machine token) — frontend-supplied user ids never select a
database.
"""

import asyncio
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from lumirss.storage import Database, DatabaseError

_current_user_id: ContextVar[str | None] = ContextVar("lumi_user_id", default=None)


class NoUserContextError(DatabaseError):
    """A private database was touched without a verified user identity."""


def current_user_id() -> str | None:
    return _current_user_id.get()


def require_user_id() -> str:
    uid = _current_user_id.get()
    if not uid:
        raise NoUserContextError("No authenticated user in this context.")
    return uid


@contextmanager
def user_context(user_id: str):
    """Bind a verified user for the enclosed block (background workers).

    Restores the previous binding on exit so nested loops never leak a
    user into the next iteration.
    """
    token = _current_user_id.set(user_id)
    try:
        yield
    finally:
        _current_user_id.reset(token)


def validate_user_id(user_id: str) -> str:
    """Defensive format check for ids that select a database file."""
    if not user_id or not user_id.isalnum() or len(user_id) > 40:
        raise NoUserContextError("Malformed user id.")
    return user_id


def bind_user_context(user_id: str) -> None:
    """Bind the user for the REST of the current request task (no scope).

    For machine-channel routes whose entire body runs as the token's
    owner: the route is the outermost task, so there is nothing to
    restore into.
    """
    _current_user_id.set(validate_user_id(user_id))


class RoutingDatabase(Database):
    """``Database`` facade that resolves each connection to the active
    user's SQLite file.

    Migrations run per user database with a per-user lock, so N users can
    lazily migrate concurrently without serializing on one asyncio.Lock.
    """

    def __init__(self, control_path: str | Path, users_root: str | Path) -> None:
        # NOTE: intentionally not calling super().__init__ with a real file;
        # the control path is kept only for diagnostics.
        super().__init__(Path(control_path))  # type: ignore[arg-type]
        self._users_root = Path(users_root)
        self._locks: dict[str, asyncio.Lock] = {}
        self._migrated_users: set[str] = set()
        self._guard = asyncio.Lock()

    # ---- path resolution -------------------------------------------------

    def user_db_path(self, user_id: str) -> Path:
        return self._users_root / validate_user_id(user_id) / "lumi.sqlite"

    def user_root(self, user_id: str) -> Path:
        return self._users_root / validate_user_id(user_id)

    @property
    def path(self) -> Path:
        uid = _current_user_id.get()
        if uid:
            return self.user_db_path(uid)
        return super().path

    def _connect(self) -> sqlite3.Connection:
        uid = require_user_id()
        try:
            self.user_db_path(uid).parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(self.user_db_path(uid)), timeout=5.0)
        except (OSError, sqlite3.Error) as exc:
            raise DatabaseError("Could not open the user database.") from exc
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error as exc:
            connection.close()
            raise DatabaseError("Could not configure the user database.") from exc
        return connection

    # ---- per-user migration bookkeeping -----------------------------------

    async def migrate(self) -> list[int]:
        uid = require_user_id()
        async with self._guard:
            lock = self._locks.get(uid)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[uid] = lock
        async with lock:
            if uid in self._migrated_users:
                return []
            from lumirss.migrations import apply_migrations

            applied = await self._run(apply_migrations, self)
            self._migrated_users.add(uid)
            return applied

    def invalidate_migration_cache(self) -> None:
        self._migrated_users.clear()

    def invalidate_user_migration(self, user_id: str) -> None:
        self._migrated_users.discard(validate_user_id(user_id))


class RoutingSecretsStore:
    """SecretsStore facade resolving to the active user's secrets file.

    Same interface as SecretsStore (get/set/delete/configured/
    configured_map) but every operation lands in
    ``<users_root>/<uid>/secrets.json`` (0600) for the context user —
    RSSHub credentials, AI keys, WebDAV and FreshRSS passwords never
    leave their owner's namespace. Construction is free; file I/O happens
    per operation exactly like the original store.
    """

    def __init__(self, users_root: str | Path) -> None:
        from lumirss.secrets_store import SecretsStore

        self._users_root = Path(users_root)
        self._store_cls = SecretsStore

    def store_for(self, user_id: str | None = None):
        uid = user_id or require_user_id()
        return self._store_cls(self._users_root / validate_user_id(uid) / "secrets.json")

    # SecretsStore-compatible surface (context-user routed) ----------------

    def get(self, key: str) -> str | None:
        return self.store_for().get(key)

    def configured(self, key: str) -> bool:
        return self.store_for().configured(key)

    def configured_map(self, keys: list[str]) -> dict[str, bool]:
        return self.store_for().configured_map(keys)

    def set(self, key: str, value: str) -> None:
        self.store_for().set(key, value)

    def delete(self, key: str) -> bool:
        return self.store_for().delete(key)

    @property
    def path(self) -> Path:
        return self.store_for().path


class UserEnv:
    """Per-request identity + binding snapshot loaded by the middleware.

    FreshRSS binding is read here (once, async) so the synchronous deps
    getters can build the per-user adapter without awaits. The API
    password itself never enters this object — the adapter reads it from
    the user's secrets store when logging in upstream.
    """

    __slots__ = ("user_id", "role", "username", "freshrss_base_url", "freshrss_username", "freshrss_public_url", "freshrss_bound")

    def __init__(self, *, user_id: str, role: str, username: str, freshrss_base_url: str = "", freshrss_username: str = "", freshrss_public_url: str = "", freshrss_bound: bool = False) -> None:
        self.user_id = user_id
        self.role = role
        self.username = username
        self.freshrss_base_url = freshrss_base_url
        self.freshrss_username = freshrss_username
        self.freshrss_public_url = freshrss_public_url
        self.freshrss_bound = freshrss_bound

    @property
    def is_admin(self) -> bool:
        return self.role in ("owner", "admin")


async def load_user_env(state, user_id: str, role: str = "member", username: str = "") -> UserEnv:
    """Read the user's FreshRSS binding (routing db, context-scoped)."""
    from lumirss.user_scope import user_context

    env = UserEnv(user_id=user_id, role=role, username=username)
    with user_context(user_id):
        try:
            await state.db.migrate()
            row = await state.db.fetch_one("SELECT base_url, username, public_url FROM freshrss_binding WHERE id = 1")
            if row is not None:
                env.freshrss_base_url = str(row["base_url"] or "")
                env.freshrss_username = str(row["username"] or "")
                env.freshrss_public_url = str(row["public_url"] or "")
                env.freshrss_bound = bool(env.freshrss_base_url and env.freshrss_username)
        except DatabaseError:
            pass  # honest unbound state; adapter creation fails with guidance
    return env


def principal_of(scope) -> dict[str, str] | None:
    """The verified principal dict stashed by the auth middleware."""
    principal = scope.get("lumi_principal")
    if isinstance(principal, dict) and principal.get("user_id"):
        return principal
    return None


async def for_each_active_user(app_state, coro_fn, *, skip_paused_check: bool = True) -> None:
    """Run ``coro_fn(uid)`` for every active user (background workers).

    Per-user failure isolation (O163): one user's broken config or upstream
    never stops the others, and every pass runs under that user's context
    so the routing database/secrets resolve correctly. Paused users are
    excluded at source (active_user_ids).
    """
    import logging

    from lumirss.accounts_store import AccountsStore

    logger = logging.getLogger("lumirss.userloop")
    try:
        uids = await AccountsStore(app_state.control_db).active_user_ids()
    except Exception:  # noqa: BLE001 — control db trouble must not kill loops
        logger.exception("background loop could not list users")
        return
    for uid in uids:
        try:
            with user_context(uid):
                await coro_fn(uid)
        except NoUserContextError:
            raise  # programming error — must be loud
        except Exception:  # noqa: BLE001 — per-user isolation
            logger.exception("background pass failed for user %s", uid)
