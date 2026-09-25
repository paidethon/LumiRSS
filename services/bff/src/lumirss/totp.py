"""两步验证（TOTP）— N007 server core.

Password login with TOTP enabled becomes two steps:

1. ``POST /auth/login`` verifies the password, then returns
   ``{"totpRequired": true, "pendingToken": ...}`` instead of a session —
   a short-lived (``PENDING_TTL_S``), single-use, hash-stored token that
   is NOT a session and grants nothing on its own;
2. ``POST /auth/totp/verify`` exchanges (pendingToken + TOTP code or
   recovery code) for a real session through the SAME minting path as
   password login, inside the SAME brute-force budget.

The TOTP shared secret lives in the per-user secrets file
(``users/<uid>/secrets.json``, chmod 0600, key ``totp_secret`` —
AD-0018-6: no secrets in SQLite). The control database keeps only
non-secret state (``totp_settings``): enabled flag, recovery-code hashes
(SHA-256 with a per-user salt) and the last-used 30-second timeslice for
replay rejection.

Replay rule: a code is accepted in its own 30s timeslice (±1 window for
clock drift); the accepted slice is recorded and any later acceptance
must be strictly greater — reusing a code, or drifting backwards, fails.
Recovery codes are single-use: the hash is removed from the table on
first successful use.
"""

import hashlib
import hmac
import json
import secrets as _secrets
import time
from datetime import UTC, datetime

import pyotp

from lumirss.storage import Database

PENDING_TTL_S = 300  # two-step login must finish within 5 minutes
RECOVERY_CODE_COUNT = 8
RECOVERY_CODE_LEN = 10  # hex chars per code
# SecretsStore 槽位名(每用户 secrets.json 内的键,非凭据本身)
TOTP_SECRET_SLOT = "totp_secret"
TOTP_STEPS = 30  # seconds (RFC 6238 default; pyotp default)
TOTP_DIGITS = 6


class TotpError(Exception):
    """Base class: stable API error types map from these."""


class TotpNotConfigured(TotpError):
    """No pending setup secret / TOTP not set up for this user."""


class TotpAlreadyEnabled(TotpError):
    """Setup attempted while TOTP is already enabled."""


class CodeInvalid(TotpError):
    """Wrong TOTP code, wrong/burnt recovery code, or replayed code."""


class PendingTokenInvalid(TotpError):
    """Unknown / expired / already-used pending login token."""


def _now() -> int:
    return int(time.time())


def _slice_at(epoch: int) -> int:
    return epoch // TOTP_STEPS


# ---- secret handling (per-user secrets file) -------------------------------


def read_secret(store) -> str | None:
    """TOTP shared secret from the routing secrets store (base32)."""
    value = store.get(TOTP_SECRET_SLOT)
    return value or None


def write_secret(store, secret: str) -> None:
    store.set(TOTP_SECRET_SLOT, secret)


def delete_secret(store) -> None:
    store.delete(TOTP_SECRET_SLOT)


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, *, username: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(
        name=username, issuer_name="LumiRSS"
    )


# ---- code verification (replay-safe) ---------------------------------------


def match_timeslice(secret: str, code: str, *, now: int | None = None) -> int | None:
    """Accepted 30s timeslice for a valid code near ``now`` (±1 window),
    or None. Checking order prefers the current slice."""
    totp = pyotp.TOTP(secret, digits=TOTP_DIGITS, interval=TOTP_STEPS)
    current = _slice_at(now if now is not None else _now())
    for delta in (0, 1, -1):
        slice_value = current + delta
        expected = totp.at(datetime.fromtimestamp(slice_value * TOTP_STEPS, tz=UTC))
        if hmac.compare_digest(str(expected), code.strip()):
            return slice_value
    return None


# ---- recovery codes ---------------------------------------------------------


def _hash_recovery_code(salt: str, code: str) -> str:
    return hashlib.sha256((salt + code).encode("utf-8")).hexdigest()


def new_recovery_codes() -> tuple[str, list[str]]:
    """(salt, plaintext_codes) — plaintext is returned to the user ONCE."""
    salt = _secrets.token_hex(16)
    codes = [_secrets.token_hex(RECOVERY_CODE_LEN // 2) for _ in range(RECOVERY_CODE_COUNT)]
    return salt, codes


def hash_recovery_codes(salt: str, codes: list[str]) -> str:
    return json.dumps([_hash_recovery_code(salt, code) for code in codes])


def match_recovery_code(row: dict[str, object], code: str) -> bool:
    """True when ``code`` matches a stored (unburnt) recovery hash."""
    salt = str(row.get("recovery_salt") or "")
    if not salt:
        return False
    try:
        hashes = json.loads(str(row.get("recovery_codes") or "[]"))
    except json.JSONDecodeError:
        return False
    candidate = _hash_recovery_code(salt, code.strip())
    return any(hmac.compare_digest(str(stored), candidate) for stored in hashes)


def burn_recovery_code(row: dict[str, object], code: str) -> None:
    """Remove one code hash; single-use by construction."""
    salt = str(row["recovery_salt"])
    hashes = json.loads(str(row.get("recovery_codes") or "[]"))
    candidate = _hash_recovery_code(salt, code.strip())
    remaining = [h for h in hashes if not hmac.compare_digest(str(h), candidate)]
    row["recovery_codes"] = json.dumps(remaining)


# ---- control-database state --------------------------------------------------


class TotpStore:
    """All TOTP SQL (inline literals + bound parameters, control DB)."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def get_settings(self, user_id: str) -> dict[str, object]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT user_id, enabled, recovery_salt, recovery_codes, last_used_timeslice FROM totp_settings WHERE user_id = ?",
            (user_id,),
        )
        if row is not None:
            return dict(row)
        return {
            "user_id": user_id,
            "enabled": 0,
            "recovery_salt": "",
            "recovery_codes": "[]",
            "last_used_timeslice": None,
        }

    async def is_enabled(self, user_id: str) -> bool:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT enabled FROM totp_settings WHERE user_id = ?", (user_id,)
        )
        return bool(row and int(row["enabled"]))

    async def save_settings(self, row: dict[str, object]) -> None:
        await self._db.execute(
            "INSERT INTO totp_settings (user_id, enabled, recovery_salt, recovery_codes, last_used_timeslice) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET enabled = excluded.enabled, recovery_salt = excluded.recovery_salt, recovery_codes = excluded.recovery_codes, last_used_timeslice = excluded.last_used_timeslice",
            (
                str(row["user_id"]),
                int(row["enabled"]),
                str(row["recovery_salt"]),
                str(row["recovery_codes"]),
                row["last_used_timeslice"],
            ),
        )

    async def disable(self, user_id: str) -> None:
        await self._db.execute(
            "DELETE FROM totp_settings WHERE user_id = ?", (user_id,)
        )

    # -- pending login tokens (NOT sessions) ---------------------------------

    async def create_pending_login(self, user_id: str) -> str:
        """One short-lived pending token; raw value returned once."""
        raw = _secrets.token_urlsafe(32)
        now = _now()
        await self._db.execute(
            "DELETE FROM totp_pending_logins WHERE expires_at <= ?", (now,)
        )
        await self._db.execute(
            "INSERT INTO totp_pending_logins (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (hashlib.sha256(raw.encode()).hexdigest(), user_id, now, now + PENDING_TTL_S),
        )
        return raw

    async def consume_pending_login(self, raw_token: str) -> str | None:
        """Burn a pending token (single-winner); user_id when valid+unexpired.

        Same shape as ``AccountsStore.redeem_invite``: a bounded read, then
        a conditional DELETE whose rowcount makes concurrent redemptions
        single-winner — a replayed token deletes nothing.
        """
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        row = await self._db.fetch_one(
            "SELECT user_id FROM totp_pending_logins WHERE token_hash = ? AND expires_at > ?",
            (token_hash, _now()),
        )
        if row is None:
            return None
        cursor = await self._db.execute(
            "DELETE FROM totp_pending_logins WHERE token_hash = ?", (token_hash,)
        )
        return str(row["user_id"]) if cursor else None

    async def purge_pending_for(self, user_id: str) -> None:
        await self._db.execute(
            "DELETE FROM totp_pending_logins WHERE user_id = ?", (user_id,)
        )


async def check_second_factor(
    control_db: Database, secrets_store, user_id: str, code: str | None, *, now: int | None = None
) -> str:
    """Sensitive-operation second factor (N007).

    Verifies a TOTP code OR recovery code for a TOTP-enabled user and
    persists the anti-replay bookkeeping (timeslice advance / recovery
    burn). Returns one of:

    - ``"not_enabled"`` — no second factor configured (caller proceeds);
    - ``"missing"``     — enabled but no code presented (caller → 400);
    - ``"invalid"``     — wrong code, replayed code, or burnt code (401);
    - ``"ok"``          — verified, bookkeeping persisted.
    """
    store = TotpStore(control_db)
    if not await store.is_enabled(user_id):
        return "not_enabled"
    if not code or not code.strip():
        return "missing"
    supplied = code.strip()
    now = now if now is not None else _now()
    row = await store.get_settings(user_id)
    # TOTP codes: exactly six digits (recovery codes are 10 hex chars).
    if len(supplied) == TOTP_DIGITS and supplied.isdigit():
        secret = read_secret(secrets_store.store_for(user_id))
        if secret:
            slice_value = match_timeslice(secret, supplied, now=now)
            if slice_value is not None:
                last = row.get("last_used_timeslice")
                if last is not None and slice_value <= int(last):
                    return "invalid"  # replayed within/behind its window
                row["last_used_timeslice"] = slice_value
                await store.save_settings(row)
                return "ok"
    if match_recovery_code(row, supplied):
        burn_recovery_code(row, supplied)
        await store.save_settings(row)
        return "ok"
    return "invalid"


__all__ = [
    "CodeInvalid",
    "PENDING_TTL_S",
    "PendingTokenInvalid",
    "TOTP_SECRET_SLOT",
    "TotpAlreadyEnabled",
    "TotpError",
    "TotpNotConfigured",
    "TotpStore",
    "burn_recovery_code",
    "check_second_factor",
    "delete_secret",
    "hash_recovery_codes",
    "match_recovery_code",
    "match_timeslice",
    "new_recovery_codes",
    "new_secret",
    "provisioning_uri",
    "read_secret",
    "write_secret",
]
