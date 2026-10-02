"""R18 — versioned RSSHub route metadata for OPML import matching.

The matching never runs untrusted JS and never scrapes docs at runtime:
it works on the vendored structured snapshot
``rsshub_routes.generated.json`` that ``scripts/export_rsshub_routes.py``
extracted from the PINNED ``diygod/rsshub@sha256:...`` image
(``/app/assets/build/routes.json`` generated inside the image). The
snapshot's ``_meta.rsshubImage`` anchors every match decision to the
exact upstream version we deploy; ``test_rsshub_catalog_upstream.py``
asserts the snapshot digest equals the docker-compose pin.

Regeneration (documented contract, same as the catalog check):

1. bump the ``diygod/rsshub@sha256:`` pin in ``docker-compose.yml``
   (and docker-compose.prod.yml);
2. ``docker pull`` the pinned image and recreate the dev rsshub
   container;
3. extend ``NAMESPACES`` in ``scripts/export_rsshub_routes.py`` if new
   namespaces should become matchable (the snapshot only carries
   namespaces Lumi curates — matching coverage is an explicit,
   reviewable list, never "all of RSSHub");
4. ``uv run python scripts/export_rsshub_routes.py`` and commit the
   refreshed snapshot together with the pin bump.

Domain mapping: upstream metadata has no site-domain column, so the
domain → namespace table below is Lumi-curated static knowledge (same
maintenance model as ``rsshub.RssHubRequires``): keyed to snapshot
namespaces, hand-verified, deliberately small. Unknown domains simply
do not match — the matcher never guesses a namespace from thin air.
"""

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

__all__ = [
    "DOMAIN_NAMESPACE_MAP",
    "UpstreamRoute",
    "routes_snapshot",
    "namespaces_for_host",
    "match_concrete_path",
    "SNAPSHOT_PATH",
]

SNAPSHOT_PATH = Path(__file__).resolve().parent / "rsshub_routes.generated.json"

# Max candidates returned for one concrete path (bounded output).
_MAX_PATH_MATCHES = 8


@dataclass(frozen=True)
class UpstreamRoute:
    """One upstream route pattern (Lumi DTO over the vendored snapshot)."""

    namespace: str
    path_pattern: str  # upstream shape: "/:param/sub?:other" style
    name: str
    example: str  # concrete example path, e.g. "/36kr/newsflashes"
    parameters: dict[str, str]  # param name → upstream description


@dataclass(frozen=True)
class PathMatch:
    """One concrete-path match: which upstream route it instantiates."""

    route: UpstreamRoute
    params: dict[str, str]  # placeholder name → decoded path segment


# Curated domain-suffix → namespaces. Suffix semantics: "36kr.com"
# matches "36kr.com" and "www.36kr.com" (exact host or dot-boundary
# suffix). Deliberately conservative — one entry per snapshot namespace
# Lumi has verified content for; unknown sites stay unmatched.
DOMAIN_NAMESPACE_MAP: dict[str, tuple[str, ...]] = {
    "36kr.com": ("36kr",),
    "cnbeta.com": ("cnbeta",),
    "coolapk.com": ("coolapk",),
    "douban.com": ("douban",),
    "github.com": ("github",),
    "huxiu.com": ("huxiu",),
    "ithome.com": ("ithome",),
    "news.ycombinator.com": ("hackernews",),
    "readhub.cn": ("readhub",),
    "sspai.com": ("sspai",),
    "v2ex.com": ("v2ex",),
    "youtube.com": ("youtube",),
    "youtu.be": ("youtube",),
    "zhihu.com": ("zhihu",),
}

# Host suffixes that must never imply a namespace (shared-hosting /
# generic TLDs could otherwise over-match future additions).
_NEVER_MATCH_SUFFIXES = ("example.com", "example.org", "localhost")

_SEGMENT_PARAM = re.compile(r"^:(\w+)(\{[^}]*\})?(\?)?$")


@lru_cache(maxsize=1)
def routes_snapshot() -> "RoutesSnapshot":
    """Parse + cache the vendored snapshot (module-lifetime singleton).

    The file is committed and versioned; a missing/corrupt snapshot is a
    repo-integrity failure surfaced by tests, so loader errors raise
    eagerly here rather than degrading matching silently.
    """
    return RoutesSnapshot._load()


class RoutesSnapshot:
    """Structured view over ``rsshub_routes.generated.json``."""

    def __init__(
        self,
        *,
        rsshub_image: str,
        schema_version: int,
        source: str,
        namespaces: dict[str, tuple[UpstreamRoute, ...]],
    ) -> None:
        self.rsshub_image = rsshub_image
        self.schema_version = schema_version
        self.source = source
        self.namespaces = namespaces

    @property
    def route_count(self) -> int:
        return sum(len(routes) for routes in self.namespaces.values())

    @classmethod
    def _load(cls) -> "RoutesSnapshot":
        raw = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        meta = raw["_meta"]
        namespaces: dict[str, tuple[UpstreamRoute, ...]] = {}
        for namespace, routes in raw["namespaces"].items():
            compiled = tuple(
                UpstreamRoute(
                    namespace=namespace,
                    path_pattern=str(pattern),
                    name=str(route.get("name") or ""),
                    example=str(route.get("example") or pattern),
                    parameters={
                        str(key): str(value)
                        for key, value in (route.get("parameters") or {}).items()
                    },
                )
                for pattern, route in routes.items()
            )
            namespaces[namespace] = compiled
        return cls(
            rsshub_image=str(meta.get("rsshubImage") or ""),
            schema_version=int(meta.get("schemaVersion") or 0),
            source=str(meta.get("source") or ""),
            namespaces=namespaces,
        )


def _pattern_regex(path_pattern: str) -> re.Pattern[str]:
    """Compile one upstream path pattern into an anchored matcher.

    Grammar (same as the catalog check's reader): ``:param`` segments
    are ``[^/]+``; a ``?`` suffix marks the segment optional; a
    ``{...}`` body is upstream's own regex hint and is intentionally
    COLLAPSED to ``[^/]+`` — matching stays structural, no upstream
    regex is ever executed. Literal segments match exactly.
    """
    parts = "^"
    for segment in path_pattern.strip("/").split("/"):
        if not segment:
            continue
        optional = segment.endswith("?")
        core = segment[:-1] if optional else segment
        param = _SEGMENT_PARAM.match(core)
        if param is not None:
            body = f"/(?P<{param.group(1)}>[^/]+)"
        else:
            body = "/" + re.escape(core)
        parts += f"(?:{body})?" if optional else body
    return re.compile(parts + "/?$")


def _route_regexes(namespace: str) -> tuple[tuple[UpstreamRoute, re.Pattern[str]], ...]:
    snapshot = routes_snapshot()
    return tuple(
        (route, _pattern_regex(route.path_pattern))
        for route in snapshot.namespaces.get(namespace, ())
    )


@lru_cache(maxsize=512)
def _cached_namespace_regexes(namespace: str) -> tuple[tuple[UpstreamRoute, re.Pattern[str]], ...]:
    return _route_regexes(namespace)


def match_concrete_path(url_path: str) -> list[PathMatch]:
    """Match a CONCRETE RSSHub path (``/sspai/matrix``) against known
    patterns; returns bounded matches with decoded placeholder values.

    Snapshot patterns are NAMESPACE-RELATIVE (``/matrix`` under
    ``sspai``), so the leading namespace segment is stripped before
    matching. The namespace must be in the snapshot; unknown namespaces
    return no matches (never a guess). Bounded to _MAX_PATH_MATCHES.
    """
    segments = url_path.strip("/").split("/", 1)
    if not segments or not segments[0]:
        return []
    namespace = segments[0]
    rest = "/" + (segments[1].rstrip("/") if len(segments) > 1 else "")
    matches: list[PathMatch] = []
    for route, regex in _cached_namespace_regexes(namespace):
        found = regex.match(rest)
        if found is None:
            continue
        matches.append(
            PathMatch(
                route=route,
                params={
                    key: value
                    for key, value in found.groupdict().items()
                    if value is not None
                },
            )
        )
        if len(matches) >= _MAX_PATH_MATCHES:
            break
    return matches


def namespaces_for_host(host: str | None) -> tuple[str, ...]:
    """Curated domain-suffix lookup: host → candidate namespaces.

    ``news.ycombinator.com`` matches exactly; ``sspai.com`` also matches
    ``www.sspai.com``. Unknown hosts and generic/example hosts match
    nothing — no fuzzy guessing.
    """
    if not host:
        return ()
    clean = host.strip().lower().rstrip(".")
    if not clean:
        return ()
    if any(clean == suffix or clean.endswith("." + suffix) for suffix in _NEVER_MATCH_SUFFIXES):
        return ()
    matched: list[str] = []
    for domain, namespaces in DOMAIN_NAMESPACE_MAP.items():
        if not namespaces:
            continue
        if clean == domain or clean.endswith("." + domain):
            for namespace in namespaces:
                if namespace not in matched:
                    matched.append(namespace)
    return tuple(matched)


def host_of(url: str) -> str | None:
    """Lowercased hostname of an http(s) URL; None otherwise."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return parts.hostname.lower()
