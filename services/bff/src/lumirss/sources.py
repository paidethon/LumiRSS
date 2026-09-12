"""Source Registry (phase2 M1) — domain-keyed resolve dispatch for ItemRefs.

Workspaces, tags, RAG and agent tools only ever hold ItemRef strings;
turning a ref into a displayable view happens here, server-side. Each
content domain registers one async resolver under its domain name; adding
a future domain (clip, snapshot, obsidian_note, …) means registering a
resolver — call sites never change. A failing RSS resolve (entry gone
from FreshRSS) degrades to ``stale=True`` instead of an error so listings
can render an honest "源已失效" placeholder without auto-deleting refs.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from lumirss.itemref import (
    LIBRARY_DOMAIN,
    RSS_DOMAIN,
    ItemRef,
    parse_item_ref,
)

_logger = logging.getLogger("lumirss.sources")

_MAX_EXCERPT_LENGTH = 280

Resolver = Callable[[str], Awaitable["ResolvedItem | None"]]


@dataclass
class ResolvedItem:
    """Unified ViewModel consumed by UnifiedContentCard (report 12 §3).

    One shape for every domain: the web client renders this, never the
    storage model. ``stale`` marks refs whose target no longer resolves.
    """

    ref: str
    domain: str
    kind: str
    title: str
    source: str
    datetime: str | None = None
    excerpt: str | None = None
    url: str | None = None
    stale: bool = False
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "domain": self.domain,
            "kind": self.kind,
            "title": self.title,
            "source": self.source,
            "datetime": self.datetime,
            "excerpt": self.excerpt,
            "url": self.url,
            "stale": self.stale,
            "payload": self.payload,
        }


def register_resolver(
    registry: dict[str, Resolver], domain: str, resolver: Resolver
) -> None:
    if domain in registry:
        raise ValueError(f"A resolver for domain '{domain}' is already registered.")
    registry[domain] = resolver


async def resolve_item(
    registry: dict[str, Resolver], ref: str
) -> ResolvedItem:
    """Resolve one ItemRef string; unknown/stale targets become stale views."""
    parsed: ItemRef = parse_item_ref(ref)
    resolver = registry.get(parsed.domain)
    if resolver is None:
        return ResolvedItem(
            ref=parsed.format(),
            domain=parsed.domain,
            kind="unknown",
            title="未知来源",
            source=parsed.domain,
            stale=True,
        )
    resolved = await resolver(parsed.key)
    if resolved is None:
        return ResolvedItem(
            ref=parsed.format(),
            domain=parsed.domain,
            kind="unknown",
            title="内容不存在",
            source=parsed.domain,
            stale=True,
        )
    return resolved


class ItemRefUnresolvable(Exception):
    """A write tried to reference content that does not resolve (ADR 0004)."""


async def ensure_resolvable(
    registry: dict[str, Resolver], ref: str
) -> ResolvedItem:
    """Validate a ref for attach-style writes (tags, favorites, workspaces).

    Only genuinely unresolvable refs are rejected — a known domain that
    currently degrades to a stale view (FreshRSS unconfigured) still
    passes, so degraded operation never bricks metadata writes.
    """
    resolved = await resolve_item(registry, ref)
    if resolved.kind == "unknown":
        raise ItemRefUnresolvable(ref)
    return resolved


def excerpt_of(text: str | None, limit: int = _MAX_EXCERPT_LENGTH) -> str | None:
    """Plain-text excerpt bound for the unified card (never HTML)."""
    if not text:
        return None
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def default_registry() -> dict[str, Resolver]:
    """Empty registry; wiring happens in deps with real services."""
    return {}


_ = LIBRARY_DOMAIN, RSS_DOMAIN  # re-exported names stay import-stable
