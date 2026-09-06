"""entryRef — LumiRSS's opaque, URL-safe reference to a FreshRSS entry.

Format: ``e1.`` + base64url(utf-8 upstream item id) without ``=``
padding — the shared envelope lives in :mod:`lumirss.opaque_ref`.

Encoding is NOT encryption, and an entryRef is not authorization: it is a
reversible, deterministic packaging of the upstream item id so that LumiRSS
URLs never depend on FreshRSS / Google Reader id shapes. Clients must treat
entryRef as an opaque string.
"""

from lumirss.opaque_ref import decode_opaque_ref, encode_opaque_ref

_REF_PREFIX = "e1."
_MAX_REF_LENGTH = 512


class InvalidEntryReference(ValueError):
    """entryRef has a wrong prefix, invalid characters, bad UTF-8, or size."""


def encode_entry_ref(item_id: str) -> str:
    """Package an upstream FreshRSS item id into an opaque entryRef."""
    if not item_id:
        raise ValueError("upstream item id must not be empty.")
    return encode_opaque_ref(_REF_PREFIX, item_id)


def decode_entry_ref(entry_ref: str) -> str:
    """Reverse of encode_entry_ref; raises InvalidEntryReference on bad input."""
    return decode_opaque_ref(
        entry_ref,
        prefix=_REF_PREFIX,
        max_length=_MAX_REF_LENGTH,
        error_type=InvalidEntryReference,
        description="entryRef",
    )
