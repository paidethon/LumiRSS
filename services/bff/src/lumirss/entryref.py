"""entryRef — LumiRSS's opaque, URL-safe reference to a FreshRSS entry.

Format: ``e1.`` + base64url(utf-8 upstream item id) without ``=`` padding.

Encoding is NOT encryption, and an entryRef is not authorization: it is a
reversible, deterministic packaging of the upstream item id so that LumiRSS
URLs never depend on FreshRSS / Google Reader id shapes. Clients must treat
entryRef as an opaque string.
"""

import base64

_REF_PREFIX = "e1."
_MAX_REF_LENGTH = 512
_BASE64URL_ALPHABET = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)


class InvalidEntryReference(ValueError):
    """entryRef has a wrong prefix, invalid characters, bad UTF-8, or size."""


def encode_entry_ref(item_id: str) -> str:
    """Package an upstream FreshRSS item id into an opaque entryRef."""
    if not item_id:
        raise ValueError("upstream item id must not be empty.")
    payload = base64.urlsafe_b64encode(item_id.encode("utf-8"))
    return _REF_PREFIX + payload.decode("ascii").rstrip("=")


def decode_entry_ref(entry_ref: str) -> str:
    """Reverse of encode_entry_ref; raises InvalidEntryReference on bad input."""
    if len(entry_ref) > _MAX_REF_LENGTH:
        raise InvalidEntryReference("entryRef is too long.")
    if not entry_ref.startswith(_REF_PREFIX):
        raise InvalidEntryReference("entryRef must start with 'e1.'.")
    payload = entry_ref[len(_REF_PREFIX):]
    if not payload or not _BASE64URL_ALPHABET.issuperset(payload):
        raise InvalidEntryReference("entryRef payload is not valid base64url.")
    padded = payload + "=" * (-len(payload) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidEntryReference("entryRef payload is not valid UTF-8.") from exc
