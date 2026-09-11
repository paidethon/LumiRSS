"""ItemRef — the unified typed reference across the RSS and Library domains.

Two and only two shapes exist:

- ``rss:<entryRef>`` — a FreshRSS entry, via the existing ``e1.`` opaque
  envelope (see :mod:`lumirss.entryref`). The entry itself stays owned by
  FreshRSS; an ItemRef is a reference, never a copy.
- ``library:<uuid>`` — a Lumi-owned LibraryItem row in ``library_items``.

Workspaces, tags, RAG chunks, agent threads and favorites only ever store
this string; resolving a ref to content goes through
:mod:`lumirss.sources` (server-side only — the web client never assembles
internal ids).

Encoding is NOT encryption and a ref is not authorization.
"""

import uuid
from dataclasses import dataclass

from lumirss.entryref import decode_entry_ref

RSS_DOMAIN = "rss"
LIBRARY_DOMAIN = "library"

_RSS_PREFIX = RSS_DOMAIN + ":"
_LIBRARY_PREFIX = LIBRARY_DOMAIN + ":"

_MAX_REF_LENGTH = 600  # entryRef envelope allows 512 incl. "e1." + "rss:"

ALLOWED_LIBRARY_KINDS = (
    "bookmark",
    "clip",
    "snapshot",
    "api_item",
    "newsletter_item",
    "obsidian_note",
)


class InvalidItemRef(ValueError):
    """ItemRef has a wrong domain prefix, invalid payload, or size."""


@dataclass(frozen=True)
class ItemRef:
    """A parsed typed reference: domain + domain-specific key."""

    domain: str
    key: str

    def format(self) -> str:
        if self.domain == RSS_DOMAIN:
            return _RSS_PREFIX + self.key
        return _LIBRARY_PREFIX + self.key


def parse_item_ref(value: str) -> ItemRef:
    """Parse and validate ``rss:…`` / ``library:…``; raises InvalidItemRef."""
    if not isinstance(value, str) or not value:
        raise InvalidItemRef("ItemRef must be a non-empty string.")
    if len(value) > _MAX_REF_LENGTH:
        raise InvalidItemRef("ItemRef is too long.")
    if value.startswith(_RSS_PREFIX):
        entry_ref = value[len(_RSS_PREFIX):]
        try:
            decode_entry_ref(entry_ref)
        except ValueError as exc:
            raise InvalidItemRef(
                "rss: ItemRef payload is not a valid entryRef."
            ) from exc
        return ItemRef(RSS_DOMAIN, entry_ref)
    if value.startswith(_LIBRARY_PREFIX):
        key = value[len(_LIBRARY_PREFIX):]
        _validate_library_key(key)
        return ItemRef(LIBRARY_DOMAIN, key)
    raise InvalidItemRef("ItemRef must start with 'rss:' or 'library:'.")


def _validate_library_key(key: str) -> None:
    try:
        uuid.UUID(key)
    except ValueError as exc:
        raise InvalidItemRef(
            "library: ItemRef payload is not a valid uuid."
        ) from exc
    if str(uuid.UUID(key)) != key:
        raise InvalidItemRef(
            "library: ItemRef payload is not in canonical uuid form."
        )


def new_library_uuid() -> str:
    """Canonical uuid string for a new library_items row."""
    return str(uuid.uuid4())


def rss_item_ref(entry_ref: str) -> str:
    """Build ``rss:<entryRef>`` after validating the entryRef."""
    return parse_item_ref(_RSS_PREFIX + entry_ref).format()


def library_item_ref(item_uuid: str) -> str:
    """Build ``library:<uuid>`` after validating the uuid."""
    return parse_item_ref(_LIBRARY_PREFIX + item_uuid).format()
