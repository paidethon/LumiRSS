"""Persistent multi-user session store (control database).

Design (matching the task's security model):

- Login passwords are verified against ``users.password_hash`` (bcrypt);
  the plaintext is never persisted anywhere. The legacy single-user
  ``auth_password`` table is only a migration source (owner_migration).
- Sessions are 256-bit ``secrets``-generated tokens handed to the browser
  as an opaque cookie. The database stores only ``SHA-256(token)`` — a
  leaked database cannot be replayed into a valid session.
- Every session row carries its ``user_id``: the middleware resolves the
  verified identity once per request and the per-user data layer reads it
  from the context (user_scope). Sessions slide: an authenticated request
  near expiry renews ``expires_at``.
- The table stays bounded per user: expired rows are pruned on login and
  a per-user live-session cap evicts the oldest ``last_seen_at`` first.
"""

import hashlib
import secrets
import time

import bcrypt

from lumirss.storage import Database

# Raw token length: token_urlsafe(32) ≈ 256 bits of entropy.
_TOKEN_BYTES = 32

# Bound on simultaneously-live sessions per user (a few devices).
MAX_LIVE_SESSIONS = 20

MIN_PASSWORD_LENGTH = 8

# Public constant hashed at build time — timing equalizer only, no secret.
_DUMMY_HASH = "$2b$12$vhJVUwWKwRIo3qc4ocmguOr4GOSWGI7L/nC8cCzWdVmM76atBdI1y"


class AuthError(Exception):
    """Base class for auth-store failures (stable API error types)."""


class InvalidCredentials(AuthError):
    """Wrong password (login/password-change currentPassword)."""


class PasswordNotInitialized(AuthError):
    """No password hash has been bootstrapped yet."""


class WeakPassword(AuthError):
    """A new password below the minimum length."""


def _hash_token(raw_token: str) -> str:
    """SHA-256 hex of the raw cookie token — the only stored form."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _now() -> int:
    return int(time.time())


class AuthStore:
    """All auth SQL lives here (inline literals + bound parameters)."""

    def __init__(self, database: Database) -> None:
        self._db = database

    # ---- password -------------------------------------------------------

    async def verify_password(self, password: str) -> None:
        """Raise InvalidCredentials / PasswordNotInitialized on failure.

        Timing: when a hash exists the bcrypt comparison dominates; when
        it does not, one dummy bcrypt check keeps the response shape
        comparable instead of a distinguishable fast-fail.
        """
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT password_hash FROM auth_password WHERE id = 1"
        )
        supplied = password.encode("utf-8")
        if row is None:
            bcrypt.checkpw(supplied, _DUMMY_HASH.encode("utf-8"))
            raise PasswordNotInitialized(
                "No password configured yet — run './lumirss set-password'."
            )
        stored = row["password_hash"]
        if not isinstance(stored, str) or not bcrypt.checkpw(
            supplied, stored.encode("utf-8")
        ):
            raise InvalidCredentials("Incorrect password.")

    async def set_password(self, new_password: str) -> None:
        """Install/replace the bcrypt hash and revoke every session."""
        if len(new_password) < MIN_PASSWORD_LENGTH:
            raise WeakPassword(
                f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
            )
        hashed = bcrypt.hashpw(
            new_password.encode("utf-8"), bcrypt.gensalt(rounds=12)
        ).decode("utf-8")
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        await self._db.execute(
            "INSERT OR REPLACE INTO auth_password (id, password_hash, updated_at) VALUES (1, ?, ?)",
            (hashed, stamp),
        )
        await self.revoke_all_sessions()

    async def has_password(self) -> bool:
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT 1 FROM auth_password WHERE id = 1")
        return row is not None

    # ---- sessions -------------------------------------------------------

    async def create_session(
        self,
        max_age_days: int,
        user_agent: str | None = None,
        *,
        user_id: str = "",
    ) -> tuple[str, int]:
        """Create a session; returns (raw_token, expires_at_epoch).

        ``user_id`` is mandatory in multi-account mode — the middleware
        uses it to bind every later request to that identity. Also prunes
        expired rows and enforces the per-user live-session cap in the
        same pass (the new row is the most recently seen, so it survives).
        """
        await self._db.migrate()
        now = _now()
        expires = now + max_age_days * 86400
        raw = secrets.token_urlsafe(_TOKEN_BYTES)
        token_hash = _hash_token(raw)
        agent = user_agent[:200] if user_agent else None
        await self._db.execute(
            "INSERT INTO auth_sessions (token_hash, created_at, last_seen_at, expires_at, user_agent, user_id) VALUES (?, ?, ?, ?, ?, ?)",
            (token_hash, now, now, expires, agent, user_id),
        )
        await self._db.execute(
            "DELETE FROM auth_sessions WHERE expires_at < ? OR (user_id = ? AND token_hash NOT IN (SELECT token_hash FROM auth_sessions WHERE user_id = ? ORDER BY last_seen_at DESC LIMIT ?))",
            (now, user_id, user_id, MAX_LIVE_SESSIONS),
        )
        return raw, expires

    async def get_valid_session_user(self, raw_token: str) -> tuple[str, int] | None:
        """(user_id, expires_at) if the token maps to an unexpired session
        whose user still exists and is active (paused users lose access
        immediately — O152)."""
        await self._db.migrate()
        token_hash = _hash_token(raw_token)
        row = await self._db.fetch_one(
            "SELECT s.expires_at AS expires_at, s.user_id AS user_id, u.status AS status FROM auth_sessions s LEFT JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?",
            (token_hash,),
        )
        if row is None:
            return None
        expires_at = int(row["expires_at"])
        if expires_at <= _now():
            return None
        user_id = str(row["user_id"] or "")
        if not user_id:
            return None
        if row["status"] is not None and str(row["status"]) != "active":
            return None
        return user_id, expires_at

    async def get_valid_session(self, raw_token: str) -> int | None:
        """Epoch expiry if the token maps to an unexpired session."""
        result = await self.get_valid_session_user(raw_token)
        return result[1] if result else None

    async def touch_session(
        self,
        raw_token: str,
        max_age_days: int,
        *,
        renew_threshold_days: int = 30,
        last_seen_granularity_s: int = 3600,
    ) -> None:
        """Sliding renewal + throttled last_seen update.

        ``expires_at`` is extended only inside the renewal window (near
        expiry); ``last_seen_at`` is written at most once per granularity
        period so an active reading session does not turn into one SQLite
        write per request.
        """
        token_hash = _hash_token(raw_token)
        row = await self._db.fetch_one(
            "SELECT last_seen_at, expires_at FROM auth_sessions WHERE token_hash = ?",
            (token_hash,),
        )
        if row is None:
            return
        now = _now()
        expires_at = int(row["expires_at"])
        renew_at = expires_at - renew_threshold_days * 86400
        if now >= renew_at:
            new_expiry = now + max_age_days * 86400
            await self._db.execute(
                "UPDATE auth_sessions SET expires_at = ?, last_seen_at = ? WHERE token_hash = ?",
                (new_expiry, now, token_hash),
            )
        elif now - int(row["last_seen_at"]) >= last_seen_granularity_s:
            await self._db.execute(
                "UPDATE auth_sessions SET last_seen_at = ? WHERE token_hash = ?",
                (now, token_hash),
            )

    async def revoke_session(self, raw_token: str) -> None:
        token_hash = _hash_token(raw_token)
        await self._db.execute(
            "DELETE FROM auth_sessions WHERE token_hash = ?", (token_hash,)
        )

    async def revoke_all_sessions(self, user_id: str | None = None) -> None:
        """Revoke every session (password change), or one user's sessions."""
        if user_id is None:
            await self._db.execute("DELETE FROM auth_sessions")
        else:
            await self._db.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))

    # ---- F038 会话管理 ----------------------------------------------------

    async def list_sessions(
        self,
        *,
        current_token: str | None = None,
        limit: int = 20,
        user_id: str | None = None,
    ) -> list[dict[str, object]]:
        """活跃会话列表（绝不返回 token 或 token_hash）。

        id = token_hash 前 8 位（显示/撤销标识）；current 按传入的原始
        token 判定；user_agent 截断 64 字符。多账户模式下每个用户只看
        得到自己的会话（user_id 必填，由服务端身份决定）。
        """
        await self._db.migrate()
        current_hash = _hash_token(current_token) if current_token else None
        if user_id is None:
            rows = await self._db.fetch_all("SELECT token_hash, created_at, last_seen_at, expires_at, user_agent FROM auth_sessions ORDER BY last_seen_at DESC LIMIT ?", (max(1, min(limit, 50)),))
        else:
            rows = await self._db.fetch_all("SELECT token_hash, created_at, last_seen_at, expires_at, user_agent FROM auth_sessions WHERE user_id = ? ORDER BY last_seen_at DESC LIMIT ?", (user_id, max(1, min(limit, 50))))
        now = _now()
        sessions: list[dict[str, object]] = []
        for row in rows:
            expires_at = int(row["expires_at"])
            if expires_at <= now:
                continue
            token_hash = str(row["token_hash"])
            agent = str(row["user_agent"] or "")
            sessions.append(
                {
                    "id": token_hash[:8],
                    "createdAt": int(row["created_at"]),
                    "lastSeenAt": int(row["last_seen_at"]),
                    "expiresAt": expires_at,
                    "userAgent": agent[:64] if agent else None,
                    "current": bool(current_hash is not None and token_hash == current_hash),
                }
            )
        return sessions

    async def revoke_session_by_id(self, session_id: str, *, user_id: str | None = None) -> bool:
        """按 8 位 id（token_hash 前缀）撤销；不存在 → False。

        多账户模式下 user_id 必传：用户只能撤销自己的会话。
        """
        if not session_id or len(session_id) != 8:
            return False
        await self._db.migrate()
        if user_id is None:
            row = await self._db.fetch_one("SELECT token_hash FROM auth_sessions WHERE token_hash LIKE ? || '%'", (session_id,))
        else:
            row = await self._db.fetch_one("SELECT token_hash FROM auth_sessions WHERE token_hash LIKE ? || '%' AND user_id = ?", (session_id, user_id))
        if row is None:
            return False
        await self._db.execute(
            "DELETE FROM auth_sessions WHERE token_hash = ?", (row["token_hash"],)
        )
        return True
