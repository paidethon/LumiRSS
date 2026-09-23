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
import json
import re
import secrets
import time

import bcrypt

from lumirss.storage import Database

_TOKEN_BYTES = 32
MIN_PASSWORD_LENGTH = 8
# bcrypt operates on at most 72 BYTES and this build of the library
# RAISES on longer input (no silent truncation) — reject over-long
# passwords with a stable 400 instead of a 500 at hash/verify time.
# Multi-byte passwords (CJK/emoji) hit the ceiling much earlier in
# characters, so the limit is bytes, not len().
MAX_PASSWORD_BYTES = 72
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,31}$")
# Public constant hashed at build time — timing equalizer only, no secret.
_DUMMY_HASH = "$2b$12$vhJVUwWKwRIo3qc4ocmguOr4GOSWGI7L/nC8cCzWdVmM76atBdI1y"

INVITE_TTL_HOURS_DEFAULT = 72
INVITE_TTL_HOURS_MAX = 24 * 30

# N004 funnel bucket sums over the aliased invites table (``i``). Same
# definitions as the totals query — pending = unused & not expired.
_BUCKET_SUMS = (
    " COUNT(*) AS generated,"
    " COALESCE(SUM(CASE WHEN i.used_at IS NOT NULL THEN 1 ELSE 0 END), 0) AS activated,"
    " COALESCE(SUM(CASE WHEN i.used_at IS NULL AND i.revoked_at IS NOT NULL THEN 1 ELSE 0 END), 0) AS revoked,"
    " COALESCE(SUM(CASE WHEN i.used_at IS NULL AND i.revoked_at IS NULL AND i.expires_at <= ? THEN 1 ELSE 0 END), 0) AS expired,"
    " COALESCE(SUM(CASE WHEN i.used_at IS NULL AND i.revoked_at IS NULL AND i.expires_at > ? THEN 1 ELSE 0 END), 0) AS pending"
)


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
    """Expired / revoked / unknown / already-used invitation.

    ``invite_id`` carries the row id when the token matched a known
    invite but was rejected (audit correlation); None for unknown
    tokens — never any token material.
    """

    def __init__(self, message: str, *, invite_id: str | None = None) -> None:
        super().__init__(message)
        self.invite_id = invite_id


class InviteNotActive(AccountError):
    """Scheduled invite redeemed before its not_before (server clock)."""

    def __init__(self, message: str, *, invite_id: str, not_before: int, now: int) -> None:
        super().__init__(message)
        self.invite_id = invite_id
        self.not_before = not_before
        self.now = now


class SchemeNotFound(AccountError):
    """Unknown invite scheme id."""


class PoolEmpty(AccountError):
    """No ready FreshRSS account in the pool (诚实状态, 不偷偷补洞)."""


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPassword("Password must be at least 8 characters.")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise WeakPassword(
            f"Password must be at most {MAX_PASSWORD_BYTES} bytes "
            "(multi-byte scripts count every byte)."
        )
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password_hash(password: str, stored: str | None) -> bool:
    """Constant-shape verification: a missing hash burns one bcrypt too.

    An over-long password can never match any storable hash (setting is
    rejected at MAX_PASSWORD_BYTES), so it burns the same dummy check and
    returns False — login fails closed with 401, never a 500.
    """
    supplied = password.encode("utf-8")
    if not stored or len(supplied) > MAX_PASSWORD_BYTES:
        bcrypt.checkpw(supplied[:MAX_PASSWORD_BYTES], _DUMMY_HASH.encode("utf-8"))
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
        """Directory listing — never includes password hashes. Includes
        the invite-scheme name (N001) as directory metadata only; a
        deleted scheme degrades to NULL, never hides the member."""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT u.id, u.username, u.role, u.status, u.display_name, u.created_at, u.updated_at, u.password_updated_at, s.name AS scheme_name"
            " FROM users u LEFT JOIN invite_schemes s ON s.id = u.scheme_id"
            " ORDER BY u.created_at ASC LIMIT ?",
            (max(1, min(limit, 500)),),
        )
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

    async def count_active_admins(self) -> int:
        """Active delegated administrators (role='admin', status='active').

        The pause guard (O152) counts ONLY delegated admins: the owner is
        a separate role that this API can never pause or demote at all,
        so a deployment with just the owner has zero removable admins and
        a deployment with one admin must keep it. Drives both the pause
        guard and the owner-only role demotion guard.
        """
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND status = 'active'")
        return int(row["n"]) if row else 0

    async def set_user_role(self, user_id: str, role: str) -> bool:
        """Owner-only role provisioning write. Returns False when the
        user does not exist; the owner row itself is never writable
        (the operator cannot demote or re-role the root account)."""
        if role not in ("owner", "admin", "member"):
            raise AccountError("Unknown role.")
        await self._db.migrate()
        cursor = await self._db.execute("UPDATE users SET role = ?, updated_at = ? WHERE id = ? AND role != 'owner'", (role, _now(), user_id))
        return bool(cursor)

    # ---- invite schemes (N001) ---------------------------------------------

    async def create_scheme(self, *, name: str, ttl_hours: int, initial_source_urls: list[str] | None = None, freshrss_pool_hold: bool = False, quota_note: str | None = None, created_by: str | None = None) -> dict[str, object]:
        """Save one named invite scheme (template for batch generation)."""
        clean_name = name.strip()
        if not clean_name:
            raise AccountError("Scheme name must not be blank.")
        ttl = max(1, min(int(ttl_hours), INVITE_TTL_HOURS_MAX))
        urls: list[str] = []
        for url in initial_source_urls or []:
            stripped = url.strip()
            if stripped and stripped not in urls:
                urls.append(stripped)
        scheme_id = f"s{secrets.token_hex(8)}"
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO invite_schemes (id, name, ttl_hours, initial_source_urls, freshrss_pool_hold, quota_note, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (scheme_id, clean_name, ttl, json.dumps(urls), 1 if freshrss_pool_hold else 0, quota_note, created_by, _now()),
        )
        scheme = await self.get_scheme(scheme_id)
        assert scheme is not None  # just inserted
        return scheme

    @staticmethod
    def _scheme_row(row: object) -> dict[str, object]:
        data: dict[str, object] = dict(row)  # pyright: ignore[reportArgumentType]
        try:
            urls = json.loads(str(data.get("initial_source_urls") or "[]"))
        except ValueError:
            urls = []
        data["initial_source_urls"] = [str(u) for u in urls] if isinstance(urls, list) else []
        return data

    async def get_scheme(self, scheme_id: str) -> dict[str, object] | None:
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT id, name, ttl_hours, initial_source_urls, freshrss_pool_hold, quota_note, created_by, created_at FROM invite_schemes WHERE id = ?", (scheme_id,))
        return self._scheme_row(row) if row else None

    async def list_schemes(self, limit: int = 200) -> list[dict[str, object]]:
        await self._db.migrate()
        rows = await self._db.fetch_all("SELECT id, name, ttl_hours, initial_source_urls, freshrss_pool_hold, quota_note, created_by, created_at FROM invite_schemes ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 500)),))
        return [self._scheme_row(r) for r in rows]

    async def delete_scheme(self, scheme_id: str) -> bool:
        """Delete a scheme template. Existing invites/accounts keep their
        scheme_id — the label degrades honestly via LEFT JOIN instead of
        being rewritten anywhere."""
        await self._db.migrate()
        cursor = await self._db.execute("DELETE FROM invite_schemes WHERE id = ?", (scheme_id,))
        return bool(cursor)

    async def set_user_scheme(self, user_id: str, scheme_id: str) -> None:
        """Record which scheme an account was activated through (N001)."""
        await self._db.migrate()
        await self._db.execute("UPDATE users SET scheme_id = ?, updated_at = ? WHERE id = ?", (scheme_id, _now(), user_id))

    # ---- invites (O146, N001/N002/N003) ------------------------------------

    async def _hold_pool_account(self) -> str:
        """Atomically move one ready pool entry to held (N003).

        Returns the FreshRSS username of the held account; raises
        PoolEmpty when nothing is ready or the candidate raced away —
        an invite is never created with a half-committed hold.
        """
        row = await self._db.fetch_one("SELECT id, freshrss_username FROM freshrss_pool WHERE state = 'ready' ORDER BY id ASC LIMIT 1")
        if row is None:
            raise PoolEmpty("No ready FreshRSS account in the pool to hold.")
        cursor = await self._db.execute("UPDATE freshrss_pool SET state = 'held', held_invite = ? WHERE id = ? AND state = 'ready'", (str(row["freshrss_username"]), int(row["id"])))
        if not cursor:  # concurrent hold grabbed it — honest failure
            raise PoolEmpty("No ready FreshRSS account in the pool to hold.")
        return str(row["freshrss_username"])

    async def _release_held_account(self, freshrss_username: str | None) -> None:
        """held → ready (revoke / expiry path). Assigned rows are never
        touched and pool rows are never deleted."""
        if not freshrss_username:
            return
        await self._db.migrate()
        await self._db.execute("UPDATE freshrss_pool SET state = 'ready', held_invite = NULL WHERE freshrss_username = ? AND state = 'held'", (freshrss_username,))

    async def release_expired_holds(self) -> int:
        """Auto-release holds of expired unused invites (N003).

        Invites expire by wall-clock comparison, so expiry release is
        enforced lazily wherever pool state is read or assigned — an
        expired invite's slot becomes reusable without any sweeper.
        """
        await self._db.migrate()
        cursor = await self._db.execute(
            "UPDATE freshrss_pool SET state = 'ready', held_invite = NULL WHERE state = 'held' AND held_invite IS NOT NULL AND EXISTS ("
            "SELECT 1 FROM invites WHERE invites.held_pool_account = freshrss_pool.freshrss_username"
            " AND invites.used_at IS NULL AND invites.revoked_at IS NULL AND invites.expires_at <= ?)",
            (_now(),),
        )
        return int(cursor or 0)

    async def create_invite(self, *, created_by: str, ttl_hours: int = INVITE_TTL_HOURS_DEFAULT, label: str | None = None, kind: str = "signup", target_user: str | None = None, scheme_id: str | None = None, not_before: int | None = None, hold_pool: bool = False) -> tuple[str, dict[str, object]]:
        """Create one invitation; returns (raw_token, invite_row).

        kind='signup' admits a new member; kind='recovery' resets the
        password of ``target_user`` (admin-initiated recovery, O150 — no
        email service required and nothing is pretended to be sent). The
        raw token appears exactly once; the database keeps its SHA-256.

        N001: ``scheme_id`` stamps the generating scheme on the row.
        N002: ``not_before`` (epoch seconds, server clock) schedules the
        earliest activation instant.
        N003: ``hold_pool`` reserves one ready FreshRSS pool account at
        creation (ready → held); raising PoolEmpty fails the whole
        create honestly instead of silently downgrading to no hold.
        """
        if kind not in ("signup", "recovery"):
            raise AccountError("Unknown invite kind.")
        if kind == "recovery" and not target_user:
            raise AccountError("Recovery invites need a target user.")
        ttl = max(1, min(int(ttl_hours), INVITE_TTL_HOURS_MAX))
        await self._db.migrate()
        held: str | None = None
        if hold_pool:
            if kind != "signup":
                raise AccountError("Only signup invites can hold a pool account.")
            held = await self._hold_pool_account()
        raw = new_token("inv")
        invite_id = f"i{secrets.token_hex(8)}"
        now = _now()
        try:
            await self._db.execute(
                "INSERT INTO invites (id, token_hash, created_by, kind, target_user, label, scheme_id, not_before, held_pool_account, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (invite_id, hash_token(raw), created_by, kind, target_user, label, scheme_id, not_before, held, now, now + ttl * 3600),
            )
        except Exception:
            if held is not None:  # never leak a hold on a failed insert
                await self._release_held_account(held)
            raise
        row = await self._db.fetch_one("SELECT id, created_by, kind, target_user, label, scheme_id, not_before, held_pool_account, created_at, expires_at FROM invites WHERE id = ?", (invite_id,))
        return raw, (dict(row) if row else {})

    async def redeem_invite(self, raw_token: str) -> dict[str, object]:
        """Atomically consume one invitation; returns its row.

        Raises InviteInvalid for unknown/expired/revoked/used tokens and
        InviteNotActive (server-clock comparison only) for scheduled
        invites redeemed before not_before (N002). The conditional
        UPDATE makes concurrent redemptions single-winner — the
        pre-checks only pick the honest error type.
        """
        await self._db.migrate()
        token_hash = hash_token(raw_token)
        now = _now()
        pre = await self._db.fetch_one("SELECT id, not_before, expires_at, used_at, revoked_at FROM invites WHERE token_hash = ?", (token_hash,))
        if pre is not None:
            invite_id = str(pre["id"])
            if pre["used_at"] is not None or pre["revoked_at"] is not None:
                raise InviteInvalid("Invitation is invalid, expired or already used.", invite_id=invite_id)
            if pre["not_before"] is not None and int(pre["not_before"]) > now:
                raise InviteNotActive("Invitation is not active yet.", invite_id=invite_id, not_before=int(pre["not_before"]), now=now)
            if int(pre["expires_at"]) <= now:
                raise InviteInvalid("Invitation is invalid, expired or already used.", invite_id=invite_id)
        cursor = await self._db.execute(
            "UPDATE invites SET used_at = ?, used_by = COALESCE(used_by, target_user) WHERE token_hash = ? AND used_at IS NULL AND revoked_at IS NULL AND expires_at > ? AND (not_before IS NULL OR not_before <= ?)",
            (now, token_hash, now, now),
        )
        if not cursor:
            raise InviteInvalid("Invitation is invalid, expired or already used.")
        row = await self._db.fetch_one("SELECT id, created_by, kind, target_user, label, scheme_id, not_before, held_pool_account, created_at, expires_at, used_at, used_by FROM invites WHERE token_hash = ?", (token_hash,))
        if row is None:
            raise InviteInvalid("Invitation is invalid.")
        return dict(row)

    async def revoke_invite(self, invite_id: str) -> bool:
        """Revoke an unused invite; its pool hold (if any) auto-releases
        back to ready (N003)."""
        await self._db.migrate()
        cursor = await self._db.execute("UPDATE invites SET revoked_at = ? WHERE id = ? AND used_at IS NULL AND revoked_at IS NULL", (_now(), invite_id))
        if cursor:
            row = await self._db.fetch_one("SELECT held_pool_account FROM invites WHERE id = ?", (invite_id,))
            if row is not None and row["held_pool_account"] is not None:
                await self._release_held_account(str(row["held_pool_account"]))
        return bool(cursor)

    async def list_invites(self, limit: int = 100) -> list[dict[str, object]]:
        await self._db.migrate()
        rows = await self._db.fetch_all("SELECT id, created_by, kind, target_user, label, scheme_id, not_before, held_pool_account, created_at, expires_at, used_at, used_by, revoked_at FROM invites ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 500)),))
        return [dict(r) for r in rows]

    async def invite_funnel(self, scheme_id: str | None = None) -> dict[str, object]:
        """Invite funnel counts from real rows (N004) — never any token
        or token hash. pending = unused and not expired (scheduled
        invites count as pending until they activate)."""
        await self._db.migrate()
        now = _now()
        filter_clause = " WHERE i.scheme_id IS ?" if scheme_id is not None else ""
        filter_params: tuple[object, ...] = (scheme_id,) if scheme_id is not None else ()
        totals_row = await self._db.fetch_one(
            "SELECT" + _BUCKET_SUMS + " FROM invites i" + filter_clause,
            (now, now, *filter_params),
        )
        data = dict(totals_row) if totals_row else {}
        totals = {key: int(data.get(key, 0) or 0) for key in ("generated", "activated", "revoked", "expired", "pending")}
        rows = await self._db.fetch_all(
            "SELECT i.scheme_id AS scheme_id, s.name AS scheme_name," + _BUCKET_SUMS
            + " FROM invites i LEFT JOIN invite_schemes s ON s.id = i.scheme_id"
            + filter_clause + " GROUP BY i.scheme_id, s.name ORDER BY generated DESC",
            (now, now, *filter_params),
        )
        by_scheme: list[dict[str, object]] = []
        for row in rows:
            grouped = dict(row)
            by_scheme.append({
                "schemeId": grouped.get("scheme_id"),
                "schemeName": grouped.get("scheme_name"),
                **{key: int(grouped.get(key, 0) or 0) for key in ("generated", "activated", "revoked", "expired", "pending")},
            })
        if scheme_id is None:
            failed_row = await self._db.fetch_one(
                "SELECT COUNT(*) AS n FROM audit_log WHERE action = 'invite_activation_failed'", ()
            )
        else:
            failed_row = await self._db.fetch_one(
                "SELECT COUNT(*) AS n FROM audit_log a JOIN invites i ON i.id = a.object_id"
                " WHERE a.action = 'invite_activation_failed' AND i.scheme_id IS ?",
                (scheme_id,),
            )
        totals["failedActivation"] = int(failed_row["n"]) if failed_row else 0
        return {"totals": totals, "byScheme": by_scheme}

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

    async def pool_assign(self, user_id: str, held_freshrss_username: str | None = None) -> dict[str, object] | None:
        """Atomically assign one ready pool entry to a user.

        When the redeeming invite holds a pool account (N003), THAT
        account is converted held → assigned first — a hold is a claim,
        never a suggestion. Falls through to the plain ready path when
        the held row is gone (already converted by a concurrent twin).
        Expired holds are swept first so an expired invite never keeps a
        slot hostage.

        Returns the assigned row or None when the pool is empty — the
        activation flow surfaces an honest "FreshRSS account not ready
        yet" state instead of falling back to shared credentials. The
        caller reads the API password from the control secrets file using
        the returned username.
        """
        await self._db.migrate()
        await self.release_expired_holds()
        if held_freshrss_username:
            row = await self._db.fetch_one("SELECT id, freshrss_username, base_url FROM freshrss_pool WHERE freshrss_username = ? AND state = 'held'", (held_freshrss_username,))
            if row is not None:
                cursor = await self._db.execute(
                    "UPDATE freshrss_pool SET state = 'assigned', held_invite = NULL, assigned_user = ?, assigned_at = ? WHERE id = ? AND state = 'held'",
                    (user_id, _now(), int(row["id"])),
                )
                if cursor:
                    return dict(row)
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
        await self.release_expired_holds()
        rows = await self._db.fetch_all("SELECT state, COUNT(*) AS n FROM freshrss_pool GROUP BY state")
        counts = {str(r["state"]): int(r["n"]) for r in rows}
        return {"ready": counts.get("ready", 0), "held": counts.get("held", 0), "assigned": counts.get("assigned", 0)}

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

    # ---- 邀请读取/修复路径（供 activation 路由使用，SQL 不出 store） ----

    async def get_invite_state_by_token(self, token_hash: str) -> dict[str, object] | None:
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT id, expires_at, not_before, used_at, revoked_at, kind FROM invites WHERE token_hash = ?", (token_hash,))
        return dict(row) if row else None

    async def restore_unused_invite(self, token_hash: str) -> None:
        """激活失败（用户名占用/弱密码）时归还一次性 token。"""
        await self._db.execute("UPDATE invites SET used_at = NULL, used_by = NULL WHERE token_hash = ?", (token_hash,))

    async def mark_invite_used_by(self, token_hash: str, user_id: str) -> None:
        await self._db.execute("UPDATE invites SET used_by = ? WHERE token_hash = ?", (user_id, token_hash))
