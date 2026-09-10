"""Persistent single-user session authentication store.

Design (matching the task's security model):

- The login password is verified against a bcrypt hash kept in
  ``auth_password``; the plaintext is never persisted anywhere. Bootstrap
  happens via ``scripts/set_password.py`` (deploy-time one-shot).
- Sessions are 256-bit ``secrets``-generated tokens handed to the browser
  as an opaque cookie. The database stores only ``SHA-256(token)`` — a
  leaked database cannot be replayed into a valid session.
- Sessions slide: an authenticated request near expiry renews
  ``expires_at``, so a regularly-used device stays logged in for up to
  ``LUMIRSS_SESSION_MAX_AGE_DAYS`` of inactivity (default 180).
- The table stays bounded: expired rows are pruned on every login, and a
  hard cap on live sessions (oldest ``last_seen_at`` evicted first) keeps
  a runaway client from growing the table forever.
"""

import hashlib
import secrets
import time

import bcrypt

from lumirss.storage import Database

# Raw token length: token_urlsafe(32) ≈ 256 bits of entropy.
_TOKEN_BYTES = 32

# Bound on simultaneously-live sessions (single user, a few devices).
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
        self, max_age_days: int, user_agent: str | None = None
    ) -> tuple[str, int]:
        """Create a session; returns (raw_token, expires_at_epoch).

        Also prunes expired rows and enforces the live-session cap in the
        same pass (the new row is the most recently seen, so it survives).
        """
        await self._db.migrate()
        now = _now()
        expires = now + max_age_days * 86400
        raw = secrets.token_urlsafe(_TOKEN_BYTES)
        token_hash = _hash_token(raw)
        agent = user_agent[:200] if user_agent else None
        await self._db.execute(
            "INSERT INTO auth_sessions (token_hash, created_at, last_seen_at, expires_at, user_agent) VALUES (?, ?, ?, ?, ?)",
            (token_hash, now, now, expires, agent),
        )
        await self._db.execute(
            "DELETE FROM auth_sessions WHERE expires_at < ? OR token_hash NOT IN (SELECT token_hash FROM auth_sessions ORDER BY last_seen_at DESC LIMIT ?)",
            (now, MAX_LIVE_SESSIONS),
        )
        return raw, expires

    async def get_valid_session(self, raw_token: str) -> int | None:
        """Epoch expiry if the token maps to an unexpired session."""
        await self._db.migrate()
        token_hash = _hash_token(raw_token)
        row = await self._db.fetch_one(
            "SELECT expires_at FROM auth_sessions WHERE token_hash = ?",
            (token_hash,),
        )
        if row is None:
            return None
        expires_at = int(row["expires_at"])
        return expires_at if expires_at > _now() else None

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

    async def revoke_all_sessions(self) -> None:
        await self._db.execute("DELETE FROM auth_sessions")
