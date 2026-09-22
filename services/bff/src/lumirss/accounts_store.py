"""Control-plane account store (0067 邀请制多账户).

Owns every identity table in the control database (LUMIRSS_DB_PATH):

- ``users`` — invite-only accounts (owner/admin/member) with bcrypt
  password hashes (same algorithm/cost as the legacy single-user store);
- ``invites`` — single-use, expiring invitation tokens; only the SHA-256
  of the raw token is stored, the raw value is shown exactly once in the
  admin create response;
- ``freshrss_pool`` — pre-provisioned FreshRSS accounts registered by the
  operator (deployment-side CLI / admin API). API passwords are encrypted
  with the secrets-derived key before they touch SQLite; assignment is a
  single atomic UPDATE so two concurrent activations can never receive the
  same account;
- ``audit_log`` — bounded operational audit (actor/action/outcome; no
  content, no credentials);
- ``token_owner_index`` — machine-channel bearer hash → user, so a token
  that arrives without a session can locate its user database.

Business data is NOT here: per-user SQLite files under
``<data_dir>/users/<uid>/`` (see user_scope.py). This store never reads
or writes user business tables. Every statement is a single-line literal
with bound parameters.
"""

import hashlib
import re
import secrets
import time

import bcrypt

from lumirss.storage import Database

_TOKEN_BYTES = 32
MIN_PASSWORD_LENGTH = 8
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,31}$")
# Public constant hashed at build time — timing equalizer only, no secret.
_DUMMY_HASH = "$2b$12$vhJVUwWKwRIo3qc4ocmguOr4GOSWGI7L/nC8cCzWdVmM76atBdI1y"

INVITE_TTL_HOURS_DEFAULT = 72
INVITE_TTL_HOURS_MAX = 24 * 30


class AccountError(Exception):
    """Base class for account-store failures (stable API error types)."""


class UsernameTaken(AccountError):
    pass


class WeakPassword(AccountError):
    pass


class InvalidUsername(AccountError):
    pass


class UserNotFound(AccountError):
    pass


class InviteInvalid(AccountError):
    """Expired / revoked / unknown / already-used invitation."""


class PoolEmpty(AccountError):
    """No ready FreshRSS account in the pool (诚实状态, 不偷偷补洞)."""


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPassword("Password must be at least 8 characters.")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password_hash(password: str, stored: str | None) -> bool:
    """Constant-shape verification: a missing hash burns one bcrypt too."""
    supplied = password.encode("utf-8")
    if not stored:
        bcrypt.checkpw(supplied, _DUMMY_HASH.encode("utf-8"))
        return False
    return bcrypt.checkpw(supplied, stored.encode("utf-8"))


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def new_token(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(_TOKEN_BYTES)}"


def _now() -> int:
    return int(time.time())


class AccountsStore:
    """All account SQL lives here (inline literals + bound parameters)."""

    def __init__(self, database: Database) -> None:
        self._db = database

    # ---- users ----------------------------------------------------------

    async def count_users(self) -> int:
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT COUNT(*) AS n FROM users")
        return int(row["n"]) if row else 0

    async def create_user(self, *, username: str, password_hash: str, role: str, display_name: str | None = None, status: str = "active") -> dict[str, object]:
        await self._db.migrate()
        if not USERNAME_RE.match(username):
            raise InvalidUsername("Username must be 3-32 chars: lowercase letters, digits, '-', '_', starting with a letter or digit.")
        uid = f"u{secrets.token_hex(8)}"
        now = _now()
        try:
            await self._db.execute("INSERT INTO users (id, username, password_hash, role, status, display_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (uid, username, password_hash, role, status, display_name, now, now))
        except Exception as exc:  # UNIQUE(username) COLLATE NOCASE
            raise UsernameTaken("Username is already taken.") from exc
        user = await self.get_user(uid)
        assert user is not None  # just inserted
        return user

    async def get_user(self, user_id: str) -> dict[str, object] | None:
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT id, username, password_hash, role, status, display_name, created_at, updated_at, password_updated_at FROM users WHERE id = ?", (user_id,))
        return dict(row) if row else None

    async def get_user_by_username(self, username: str) -> dict[str, object] | None:
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT id, username, password_hash, role, status, display_name, created_at, updated_at, password_updated_at FROM users WHERE username = ?", (username,))
        return dict(row) if row else None

    async def list_users(self, limit: int = 200) -> list[dict[str, object]]:
        """Directory listing — never includes password hashes."""
        await self._db.migrate()
        rows = await self._db.fetch_all("SELECT id, username, role, status, display_name, created_at, updated_at, password_updated_at FROM users ORDER BY created_at ASC LIMIT ?", (max(1, min(limit, 500)),))
        return [dict(r) for r in rows]

    async def set_user_status(self, user_id: str, status: str) -> bool:
        """Pause / resume. Returns False when the user does not exist."""
        if status not in ("active", "paused"):
            raise AccountError("Unknown status.")
        await self._db.migrate()
        cursor = await self._db.execute("UPDATE users SET status = ?, updated_at = ? WHERE id = ? AND role != 'owner'", (status, _now(), user_id))
        return bool(cursor)

    async def set_password_hash(self, user_id: str, password_hash: str) -> None:
        await self._db.migrate()
        await self._db.execute("UPDATE users SET password_hash = ?, password_updated_at = ?, updated_at = ? WHERE id = ?", (password_hash, _now(), _now(), user_id))

    async def verify_login(self, username: str, password: str) -> dict[str, object] | None:
        """Return the user row on success, None on any failure.

        Unknown usernames burn one bcrypt check too — no account-existence
        oracle through timing (O171). Paused users cannot log in.
        """
        await self._db.migrate()
        user = await self.get_user_by_username(username.strip().lower())
        stored = user["password_hash"] if user else None
        ok = verify_password_hash(password, stored if isinstance(stored, str) else None)
        if user is None or not ok:
            return None
        if user["status"] != "active":
            return None
        return user

    async def active_user_ids(self) -> list[str]:
        """All active user ids (background loops iterate these)."""
        await self._db.migrate()
        rows = await self._db.fetch_all("SELECT id FROM users WHERE status = 'active' ORDER BY created_at ASC")
        return [str(r["id"]) for r in rows]

    # ---- invites (O146) ---------------------------------------------------

    async def create_invite(self, *, created_by: str, ttl_hours: int = INVITE_TTL_HOURS_DEFAULT, label: str | None = None, kind: str = "signup", target_user: str | None = None) -> tuple[str, dict[str, object]]:
        """Create one invitation; returns (raw_token, invite_row).

        kind='signup' admits a new member; kind='recovery' resets the
        password of ``target_user`` (admin-initiated recovery, O150 — no
        email service required and nothing is pretended to be sent). The
        raw token appears exactly once; the database keeps its SHA-256.
        """
        if kind not in ("signup", "recovery"):
            raise AccountError("Unknown invite kind.")
        if kind == "recovery" and not target_user:
            raise AccountError("Recovery invites need a target user.")
        ttl = max(1, min(int(ttl_hours), INVITE_TTL_HOURS_MAX))
        await self._db.migrate()
        raw = new_token("inv")
        invite_id = f"i{secrets.token_hex(8)}"
        now = _now()
        await self._db.execute("INSERT INTO invites (id, token_hash, created_by, kind, target_user, label, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (invite_id, hash_token(raw), created_by, kind, target_user, label, now, now + ttl * 3600))
        row = await self._db.fetch_one("SELECT id, created_by, kind, target_user, label, created_at, expires_at FROM invites WHERE id = ?", (invite_id,))
        return raw, (dict(row) if row else {})

    async def redeem_invite(self, raw_token: str) -> dict[str, object]:
        """Atomically consume one invitation; returns its row.

        Raises InviteInvalid for unknown/expired/revoked/used tokens. The
        conditional UPDATE makes concurrent redemptions single-winner.
        """
        await self._db.migrate()
        token_hash = hash_token(raw_token)
        now = _now()
        cursor = await self._db.execute("UPDATE invites SET used_at = ?, used_by = COALESCE(used_by, target_user) WHERE token_hash = ? AND used_at IS NULL AND revoked_at IS NULL AND expires_at > ?", (now, token_hash, now))
        if not cursor:
            raise InviteInvalid("Invitation is invalid, expired or already used.")
        row = await self._db.fetch_one("SELECT id, created_by, kind, target_user, label, created_at, expires_at, used_at, used_by FROM invites WHERE token_hash = ?", (token_hash,))
        if row is None:
            raise InviteInvalid("Invitation is invalid.")
        return dict(row)

    async def revoke_invite(self, invite_id: str) -> bool:
        await self._db.migrate()
        cursor = await self._db.execute("UPDATE invites SET revoked_at = ? WHERE id = ? AND used_at IS NULL AND revoked_at IS NULL", (_now(), invite_id))
        return bool(cursor)

    async def list_invites(self, limit: int = 100) -> list[dict[str, object]]:
        await self._db.migrate()
        rows = await self._db.fetch_all("SELECT id, created_by, kind, target_user, label, created_at, expires_at, used_at, used_by, revoked_at FROM invites ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 500)),))
        return [dict(r) for r in rows]

    # ---- FreshRSS pool (O155) ---------------------------------------------

    async def pool_add(self, *, base_url: str, freshrss_username: str) -> dict[str, object]:
        """Register one pre-provisioned FreshRSS account.

        The API password is NOT stored here — the caller keeps it in the
        control-level secrets file (0600, key ``freshrss_pool:<username>``,
        AD-0018-6: no secrets in SQLite).
        """
        await self._db.migrate()
        now = _now()
        try:
            await self._db.execute("INSERT INTO freshrss_pool (freshrss_username, base_url, state, created_at) VALUES (?, ?, 'ready', ?)", (freshrss_username, base_url, now))
        except Exception as exc:
            raise AccountError("This FreshRSS account is already registered.") from exc
        row = await self._db.fetch_one("SELECT id, freshrss_username, base_url, state, created_at FROM freshrss_pool WHERE freshrss_username = ?", (freshrss_username,))
        return dict(row) if row else {}

    async def pool_assign(self, user_id: str) -> dict[str, object] | None:
        """Atomically assign one ready pool entry to a user.

        Returns the assigned row or None when the pool is empty — the
        activation flow surfaces an honest "FreshRSS account not ready
        yet" state instead of falling back to shared credentials. The
        caller reads the API password from the control secrets file using
        the returned username.
        """
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT id, freshrss_username, base_url FROM freshrss_pool WHERE state = 'ready' ORDER BY id ASC LIMIT 1")
        if row is None:
            return None
        cursor = await self._db.execute("UPDATE freshrss_pool SET state = 'assigned', assigned_user = ?, assigned_at = ? WHERE id = ? AND state = 'ready'", (user_id, _now(), int(row["id"])))
        if not cursor:  # concurrent assignment grabbed it — honest retry signal
            return None
        return dict(row)

    async def pool_release(self, user_id: str) -> None:
        """Return a user's assigned-but-unused entry to the pool (failure path)."""
        await self._db.migrate()
        await self._db.execute("UPDATE freshrss_pool SET state = 'ready', assigned_user = NULL, assigned_at = NULL WHERE assigned_user = ? AND state = 'assigned'", (user_id,))

    async def pool_status(self) -> dict[str, int]:
        await self._db.migrate()
        rows = await self._db.fetch_all("SELECT state, COUNT(*) AS n FROM freshrss_pool GROUP BY state")
        counts = {str(r["state"]): int(r["n"]) for r in rows}
        return {"ready": counts.get("ready", 0), "assigned": counts.get("assigned", 0)}

    # ---- audit (O172) -------------------------------------------------------

    async def audit(self, *, actor: str, action: str, object_type: str | None = None, object_id: str | None = None, outcome: str = "ok", detail: str | None = None) -> None:
        """Best-effort audit write — must never break the request path."""
        try:
            await self._db.migrate()
            await self._db.execute("INSERT INTO audit_log (ts, actor, action, object_type, object_id, outcome, detail) VALUES (?, ?, ?, ?, ?, ?, ?)", (_now(), actor, action, object_type, object_id, outcome, detail))
        except Exception:  # noqa: BLE001 — audit is advisory
            pass

    async def audit_list(self, limit: int = 100) -> list[dict[str, object]]:
        await self._db.migrate()
        rows = await self._db.fetch_all("SELECT ts, actor, action, object_type, object_id, outcome, detail FROM audit_log ORDER BY id DESC LIMIT ?", (max(1, min(limit, 500)),))
        return [dict(r) for r in rows]

    # ---- machine-token index ---------------------------------------------

    async def index_token(self, token_hash: str, user_id: str, purpose: str) -> None:
        await self._db.migrate()
        await self._db.execute("INSERT OR REPLACE INTO token_owner_index (token_hash, user_id, purpose, created_at) VALUES (?, ?, ?, ?)", (token_hash, user_id, purpose, _now()))

    async def token_owner(self, token_hash: str) -> str | None:
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT user_id FROM token_owner_index WHERE token_hash = ?", (token_hash,))
        return str(row["user_id"]) if row else None
