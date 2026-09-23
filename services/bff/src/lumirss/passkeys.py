"""通行密钥（WebAuthn passkeys）— N006 server core.

Real WebAuthn verification on top of python-fido2 (Yubico) ``Fido2Server``:
RP ID hash, origin, challenge binding, user-presence flag and assertion
signature are all checked by the library; clone detection (sign counter
monotonicity) is enforced here because fido2 2.x leaves the stored-counter
comparison to the caller.

Deterministic RP / origin rule (documented contract):

- ``LUMIRSS_PUBLIC_ORIGIN`` configured → RP ID = the configured URL's
  host, and the ONLY accepted origin is that exact URL (deployments
  behind header-rewriting proxies must set it);
- otherwise RP ID = the request ``Host`` header's hostname (port
  stripped), and accepted origins are ``http://<host>`` / ``https://<host>``
  (host including a non-default port). Same rule as the CSRF Origin gate
  in middleware, so a deployment that works for cookies works for passkeys.

Challenges are single-use rows in the control database
(webauthn_challenges, TTL ≈ 5 min) consumed by the router with an atomic
conditional DELETE before the synchronous fido2 verification runs — a
replayed or expired challenge simply deletes nothing. Credentials live in
``webauthn_credentials`` (public key material only — private keys never
leave the authenticator); the API surface never echoes key bytes.
"""

import secrets as _secrets
import time
from typing import Any
from urllib.parse import urlsplit

from fido2 import cbor as _cbor
from fido2.cose import CoseKey
from fido2.server import Fido2Server
from fido2.utils import websafe_decode, websafe_encode
from fido2.webauthn import (
    AttestedCredentialData,
    AuthenticationResponse,
    AuthenticatorData,
    PublicKeyCredentialDescriptor,
    PublicKeyCredentialRpEntity,
    PublicKeyCredentialType,
    PublicKeyCredentialUserEntity,
)

from lumirss.config import LumiSettings
from lumirss.storage import Database

CHALLENGE_TTL_S = 300  # ~5 minutes: enough for a slow user, useless to replay


class PasskeyError(Exception):
    """Base class: stable API error types map from these."""


class ChallengeInvalid(PasskeyError):
    """Unknown / expired / replayed / wrong-purpose challenge."""


class VerificationFailed(PasskeyError):
    """Attestation/assertion failed cryptographic or binding checks."""


def _now() -> int:
    return int(time.time())


# ---- RP / origin derivation (deterministic rule) --------------------------


def rp_and_origins(request) -> tuple[str, set[str]]:
    """(rp_id, accepted_origins) for this request — see module docstring."""
    configured = LumiSettings().LUMIRSS_PUBLIC_ORIGIN.strip()
    if configured:
        parts = urlsplit(configured)
        return (parts.hostname or parts.netloc, {configured})
    host = ""
    for key, value in request.headers.raw:
        if key == b"host":
            host = value.decode("latin-1").strip().lower()
            break
    rp_id = host.split(":", 1)[0] if host else "localhost"
    return rp_id, {f"http://{host or 'localhost'}", f"https://{host or 'localhost'}"}


def _build_server(rp_id: str, origins: set[str]) -> Fido2Server:
    return Fido2Server(
        PublicKeyCredentialRpEntity(id=rp_id, name="LumiRSS"),
        attestation="none",  # self-hosted RP: no attestation trust store (spec "none")
        verify_origin=lambda origin: origin in origins,
    )


# ---- store: challenges + credentials (control database) -------------------


class PasskeyStore:
    """All WebAuthn SQL (inline literals + bound parameters, control DB)."""

    def __init__(self, database: Database) -> None:
        self._db = database

    # -- challenges -------------------------------------------------------

    async def put_challenge(self, challenge: str, *, user_id: str, purpose: str) -> None:
        # Sweep-up in the same pass keeps the table bounded without a
        # background job: expired rows are useless by construction.
        await self._db.execute(
            "DELETE FROM webauthn_challenges WHERE expires_at <= ?", (_now(),)
        )
        await self._db.execute(
            "INSERT OR REPLACE INTO webauthn_challenges (challenge, user_id, purpose, expires_at) VALUES (?, ?, ?, ?)",
            (challenge, user_id, purpose, _now() + CHALLENGE_TTL_S),
        )

    async def consume_challenge(
        self, challenge: str, *, purpose: str, user_id: str | None = None
    ) -> dict[str, object] | None:
        """Atomically burn one challenge row; None when absent/expired.

        Same single-winner shape as ``AccountsStore.redeem_invite``: a
        bounded read (expiry / purpose / owner narrowed), then a
        conditional DELETE whose rowcount makes concurrent consumption
        single-winner — a replayed challenge deletes nothing. The row
        (with its user binding) is returned for the caller's checks.

        ``user_id`` narrows the read to one owner (register flow). An
        empty stored user_id (unbound login challenge for an unknown
        username) matches only when the caller passes user_id=None.
        """
        sql = "SELECT user_id FROM webauthn_challenges WHERE challenge = ? AND purpose = ? AND expires_at > ?"
        params: list[Any] = [challenge, purpose, _now()]
        if user_id is not None:
            sql += " AND user_id = ?"
            params.append(user_id)
        row = await self._db.fetch_one(sql, tuple(params))
        if row is None:
            return None
        cursor = await self._db.execute(
            "DELETE FROM webauthn_challenges WHERE challenge = ?", (challenge,)
        )
        return dict(row) if cursor else None

    # -- credentials --------------------------------------------------------

    async def create_credential(
        self,
        *,
        credential_id: str,
        user_id: str,
        label: str,
        public_key: str,
        sign_count: int,
    ) -> dict[str, object]:
        """Insert one credential; returns the API-safe view (no key bytes)."""
        now = _now()
        await self._db.execute(
            "INSERT INTO webauthn_credentials (id, user_id, label, public_key, sign_count, created_at, last_used_at) VALUES (?, ?, ?, ?, ?, ?, NULL)",
            (credential_id, user_id, label[:64], public_key, sign_count, now),
        )
        return {"id": credential_id, "label": label[:64], "createdAt": now, "lastUsedAt": None}

    async def list_credentials(self, *, user_id: str) -> list[dict[str, object]]:
        """API-safe listing: id / label / createdAt / lastUsedAt ONLY."""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, label, created_at, last_used_at FROM webauthn_credentials WHERE user_id = ? ORDER BY created_at ASC",
            (user_id,),
        )
        return [
            {
                "id": str(row["id"]),
                "label": str(row["label"] or ""),
                "createdAt": int(row["created_at"]),
                "lastUsedAt": int(row["last_used_at"]) if row["last_used_at"] is not None else None,
            }
            for row in rows
        ]

    async def get_credential(self, credential_id: str) -> dict[str, object] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, user_id, label, public_key, sign_count FROM webauthn_credentials WHERE id = ?",
            (credential_id,),
        )
        return dict(row) if row else None

    async def credential_ids(self, *, user_id: str) -> list[str]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id FROM webauthn_credentials WHERE user_id = ?", (user_id,)
        )
        return [str(row["id"]) for row in rows]

    async def delete_credential(self, credential_id: str, *, user_id: str) -> bool:
        cursor = await self._db.execute(
            "DELETE FROM webauthn_credentials WHERE id = ? AND user_id = ?",
            (credential_id, user_id),
        )
        return bool(cursor)

    async def record_usage(self, credential_id: str, *, sign_count: int) -> None:
        await self._db.execute(
            "UPDATE webauthn_credentials SET sign_count = ?, last_used_at = ? WHERE id = ?",
            (sign_count, _now(), credential_id),
        )


# ---- WebAuthn ceremony helpers (sync — fido2 surface is synchronous) -------

_STATE_TTL_NOTE = "state carries the STORED challenge form (websafe string); the DB row is the single source of truth"


def _state_for(challenge: str) -> dict[str, Any]:
    """fido2 internal state shape: ``websafe_encode(challenge)`` + UV level.

    Fido2Server compares ``websafe_decode(state["challenge"])`` against the
    client data, so passing the stored base64url row value directly keeps
    the database row the single source of truth for the ceremony.
    """
    return {"challenge": challenge, "user_verification": None}


def new_challenge() -> str:
    return websafe_encode(_secrets.token_bytes(32))


def begin_registration(
    request,
    *,
    challenge: str,
    user_id: str,
    username: str,
    display_name: str,
    exclude_ids: list[str],
) -> dict[str, Any]:
    """Registration ceremony options (``publicKey`` payload).

    ``exclude_ids`` lists the user's existing credentials so the same
    authenticator is not re-registered.
    """
    rp_id, _origins = rp_and_origins(request)
    server = _build_server(rp_id, _origins)
    options, _state = server.register_begin(
        PublicKeyCredentialUserEntity(
            id=user_id.encode("utf-8"),
            name=username,
            display_name=display_name or username,
        ),
        credentials=[
            PublicKeyCredentialDescriptor(
                type=PublicKeyCredentialType.PUBLIC_KEY, id=websafe_decode(cid)
            )
            for cid in exclude_ids
        ],
        challenge=websafe_decode(challenge),
    )
    return {"publicKey": dict(options.public_key)}


def finish_registration(
    request, *, challenge: str, response: dict[str, Any]
) -> tuple[str, str, int]:
    """Verify a registration response (challenge already burned by the
    router); returns (credential_id_b64, cose_public_key_b64, sign_count).
    Raises VerificationFailed on any binding/signature failure."""
    rp_id, origins = rp_and_origins(request)
    server = _build_server(rp_id, origins)
    try:
        auth_data: AuthenticatorData = server.register_complete(
            _state_for(challenge), response
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise VerificationFailed("注册响应验证失败。") from exc
    credential_data = auth_data.credential_data
    if credential_data is None:  # pragma: no cover — lib requires the AT flag
        raise VerificationFailed("注册响应缺少凭据公钥。")
    cose_blob = websafe_encode(_cbor.encode(credential_data.public_key))
    return (
        websafe_encode(credential_data.credential_id),
        cose_blob,
        int(auth_data.counter),
    )


def begin_login(
    request, *, challenge: str, allowed_ids: list[str]
) -> dict[str, Any]:
    """Login ceremony options. Empty ``allowed_ids`` (unknown username, or
    user without passkeys) yields the SAME generic shape — no user
    enumeration; the browser may then offer any discoverable credential
    for this RP and the server verifies it against the database."""
    rp_id, _origins = rp_and_origins(request)
    server = _build_server(rp_id, _origins)
    options, _state = server.authenticate_begin(
        [
            PublicKeyCredentialDescriptor(
                type=PublicKeyCredentialType.PUBLIC_KEY, id=websafe_decode(cid)
            )
            for cid in allowed_ids
        ],
        challenge=websafe_decode(challenge),
    )
    return {"publicKey": dict(options.public_key)}


def finish_login(
    request,
    *,
    challenge: str,
    credential_row: dict[str, object],
    response: dict[str, Any],
) -> int:
    """Verify an assertion against one stored credential (challenge
    already burned by the router). Returns the NEW sign counter to
    persist. Clone rule: when the stored counter is > 0 the new counter
    must be strictly greater — a repeated or backwards counter means a
    cloned authenticator. Counter-less authenticators (always 0) are
    accepted as-is per the WebAuthn spec. Raises VerificationFailed."""
    rp_id, origins = rp_and_origins(request)
    server = _build_server(rp_id, origins)
    try:
        credential_data = AttestedCredentialData.create(
            bytes(16),  # AAGUID is not verified; the stored key is what counts
            websafe_decode(str(credential_row["id"])),
            CoseKey.parse(
                _cbor.decode(websafe_decode(str(credential_row["public_key"])))
            ),
        )
        parsed = AuthenticationResponse.from_dict(response)
        auth_data: AuthenticatorData = parsed.response.authenticator_data
        server.authenticate_complete(_state_for(challenge), [credential_data], response)
    except (ValueError, KeyError, TypeError) as exc:
        raise VerificationFailed("断言验证失败。") from exc
    new_counter = int(auth_data.counter)
    stored_counter = int(credential_row["sign_count"] or 0)
    if stored_counter > 0 and new_counter <= stored_counter:
        raise VerificationFailed("凭据计数异常（疑似克隆）。")
    return new_counter


__all__ = [
    "CHALLENGE_TTL_S",
    "ChallengeInvalid",
    "PasskeyError",
    "PasskeyStore",
    "VerificationFailed",
    "begin_login",
    "begin_registration",
    "finish_login",
    "finish_registration",
    "new_challenge",
    "rp_and_origins",
]
