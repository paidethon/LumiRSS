"""N130 来源秘密轮换预演 — credential probe + fallback window.

Two credentials participate in rotation:

- the LIVE credential hash in the owning table (``api_sources.secret`` /
  ``inbox_sources.secret``, SHA-256 hex since §13.4);
- the OLD credential hash, parked in the user's SecretsStore under a
  rotation key for a bounded FALLBACK WINDOW (10 minutes) right after a
  successful swap. Reads always verify the NEW credential first; only
  when it fails ONCE does the fallback get consulted — and a fallback
  hit is flagged on the source so the operator sees that a client is
  still on the old secret. A lazy sweep prunes expired entries on every
  touch, so no background job is needed.

The plaintext new credential NEVER persists anywhere: the probe uses it
in memory only, storage keeps hashes, responses are masked
(``{ok, statusClass, latencyMs}`` — no echo of the credential or any
request/response header).
"""

import json
import re
from datetime import UTC, datetime, timedelta

from lumirss.secrets_store import SecretsStore
from lumirss.token_hash import verify_token
from lumirss.util import utc_now

FALLBACK_WINDOW_SECONDS = 600  # 10 minutes

_CREDENTIAL_SHAPE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")

API_SOURCE_KIND = "api_source"
INBOX_SOURCE_KIND = "inbox_ingest"


class CredentialTestFailed(Exception):
    """The proposed new credential failed the dry probe (422 stable)."""

    def __init__(self, status_class: str, message: str) -> None:
        super().__init__(message)
        self.status_class = status_class


def validate_credential_shape(new_credential: object) -> str:
    """Structural gate before anything else: 16..128 chars of
    [A-Za-z0-9_-], no whitespace. A weak credential is a test failure,
    not a crash."""
    if not isinstance(new_credential, str) or not _CREDENTIAL_SHAPE.match(
        new_credential
    ):
        raise CredentialTestFailed(
            "invalid_credential",
            "新凭据必须是 16..128 个字母/数字/连字符/下划线字符（不含空格）。",
        )
    return new_credential


def fallback_key(kind: str, source_uuid: str) -> str:
    return f"credential_fallback:{kind}:{source_uuid}"


def store_fallback(
    secrets: SecretsStore, kind: str, source_uuid: str, old_credential_hash: str
) -> None:
    """Park the OLD credential hash for the fallback window. Only the
    hash is stored (§13.4 holds for the fallback too)."""
    payload = json.dumps(
        {"hash": old_credential_hash, "rotated_at": utc_now()},
        ensure_ascii=False,
        sort_keys=True,
    )
    secrets.set(fallback_key(kind, source_uuid), payload)


def sweep_expired(secrets: SecretsStore, kind: str, source_uuid: str) -> None:
    """Lazy sweep: drop the fallback entry once its window has passed."""
    key = fallback_key(kind, source_uuid)
    raw = secrets.get(key)
    if raw is None:
        return
    try:
        parsed = json.loads(raw)
        rotated_at = str(parsed["rotated_at"])
    except (json.JSONDecodeError, KeyError, TypeError):
        secrets.delete(key)
        return
    try:
        rotated = datetime.fromisoformat(rotated_at.replace("Z", "+00:00"))
    except ValueError:
        secrets.delete(key)
        return
    if rotated.tzinfo is None:
        rotated = rotated.replace(tzinfo=UTC)
    if datetime.now(UTC) - rotated >= timedelta(
        seconds=FALLBACK_WINDOW_SECONDS
    ):
        secrets.delete(key)


def match_fallback(
    secrets: SecretsStore, kind: str, source_uuid: str, presented: str
) -> bool:
    """True when ``presented`` matches the (unexpired) fallback hash.

    Expiry is checked lazily right here — an expired entry is swept and
    answers False, so the fallback window closes itself without a
    background job."""
    sweep_expired(secrets, kind, source_uuid)
    raw = secrets.get(fallback_key(kind, source_uuid))
    if raw is None:
        return False
    try:
        parsed = json.loads(raw)
        old_hash = str(parsed["hash"])
    except (json.JSONDecodeError, KeyError, TypeError):
        return False
    return verify_token(presented, old_hash)


def drop_fallback(secrets: SecretsStore, kind: str, source_uuid: str) -> None:
    secrets.delete(fallback_key(kind, source_uuid))


def fallback_still_stored(secrets: SecretsStore, kind: str, source_uuid: str) -> bool:
    """Test helper visibility: is a fallback entry parked (unexpired)?"""
    sweep_expired(secrets, kind, source_uuid)
    return secrets.get(fallback_key(kind, source_uuid)) is not None
