"""Shared opaque-reference packaging mechanics.

LumiRSS's three opaque refs — pagination cursor (``c1.``), entryRef
(``e1.``), subscriptionRef (``s1.``) — share one envelope: a version
prefix + base64url(utf-8 payload) without ``=`` padding, guarded by
prefix / length / alphabet checks. This module owns the envelope only;
each ref module owns its payload schema and public error type.

Encoding is NOT encryption, and a ref is never authorization: it is a
reversible, deterministic packaging so that Lumi URLs never depend on
FreshRSS id shapes. Clients must treat refs as opaque strings.
"""

import base64

BASE64URL_ALPHABET = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)


def encode_opaque_ref(prefix: str, payload: str) -> str:
    """Package a utf-8 payload under ``prefix`` (envelope only)."""
    encoded = base64.urlsafe_b64encode(payload.encode("utf-8"))
    return prefix + encoded.decode("ascii").rstrip("=")


def decode_opaque_ref(
    value: str,
    *,
    prefix: str,
    max_length: int,
    error_type: type[ValueError],
    description: str,
) -> str:
    """Reverse of encode_opaque_ref; raises ``error_type`` on bad input.

    Validates the envelope (length, prefix, base64url alphabet, UTF-8);
    payload-schema validation stays with the caller-specific ref module.
    """
    if len(value) > max_length:
        raise error_type(f"{description} is too long.")
    if not value.startswith(prefix):
        raise error_type(f"{description} must start with {prefix!r}.")
    raw = value[len(prefix):]
    if not raw or not BASE64URL_ALPHABET.issuperset(raw):
        raise error_type(f"{description} payload is not valid base64url.")
    padded = raw + "=" * (-len(raw) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise error_type(f"{description} payload is not valid UTF-8.") from exc
