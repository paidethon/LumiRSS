"""R18 — OPML 订阅 → RSSHub 路由匹配器（结构化数据 + 受限解析）。

输入一条 OPML 条目的 xmlUrl（可选 htmlUrl），输出候选路由列表与
自动决策建议。约束（与任务书一致）：

- **不在 BFF 执行不可信 JS**：规则匹配只用 vendored 快照的结构化
  数据（``rsshub_routes_data``）+ stdlib 正则 / URL 解析；
- **置信度分档**：high（xmlUrl 路径可具体实例化某条路由且参数齐备）、
  medium（仅站点域名命中命名空间，或多个路由并列存疑）、low 保留
  给未来扩展（当前不产生 low 候选）；
- **同域误配防护**：同一命名空间下多条路由都能解释路径时（如
  36kr 的 ``/:category/…`` vs ``/hot-list/:category?``），一律降级为
  medium + ambiguous → 人工选择，绝不自动挑一个；
- **凭据诚实**：路由依赖来自 Lumi curated 静态知识
  （``NAMESPACE_REQUIRES``，与 rsshub.RssHubRequires 同一维护模型）；
  True = 需要 / None = 未知 / False = 不需要。已知需要凭据的候选
  标记 needs_credentials，导入流不会静默替换。

唯一「high 且无歧义且参数齐备且不需凭据」的候选才给 auto 建议；
其余情形由导入流降级为人工选择或保持原生。
"""

import re
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

from lumirss.rsshub_routes_data import (
    UpstreamRoute,
    _pattern_regex,
    host_of,
    match_concrete_path,
    namespaces_for_host,
    routes_snapshot,
)

__all__ = [
    "CONFIDENCE_HIGH",
    "CONFIDENCE_MEDIUM",
    "MatchCandidate",
    "MatchOutcome",
    "MissingRouteParams",
    "UnsafeRoutePath",
    "instantiate_route",
    "match_source",
    "classify_feed_url",
]

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"

# Common feed-file suffixes: an xmlUrl of exactly one of these points at
# the site's root feed — the informative path part is empty.
_FEED_FILE_SUFFIXES = (
    "rss",
    "rss.xml",
    "feed",
    "feed.xml",
    "atom",
    "atom.xml",
    "index.xml",
    "index.atom",
)

# Lumi-curated per-namespace credential knowledge (same maintenance
# model as rsshub.RssHubRequires; None facet = unknown, honestly).
# Keyed to snapshot namespaces; unlisted namespaces → unknown.
NAMESPACE_REQUIRES: dict[str, dict[str, bool | None]] = {
    "zhihu": {"cookies": True},
    "coolapk": {"cookies": True},
    "youtube": {"extra_service": True},
    "douban": {"cookies": None},
}

# Scans placeholders across a WHOLE multi-segment pattern (unanchored).
_PARAM_TOKEN = re.compile(r":(\w+)(\{[^}]*\})?(\?)?")
# Matches ONE path segment that is a placeholder (anchored).
_PARAM_SEGMENT = re.compile(r"^:(\w+)(\{[^}]*\})?(\?)?$")


class MissingRouteParams(Exception):
    """A candidate route needs required parameters that are not derivable."""

    def __init__(self, names: tuple[str, ...]) -> None:
        super().__init__(f"missing route parameter(s): {', '.join(names)}")
        self.names = names


class UnsafeRoutePath(Exception):
    """Instantiating a route produced a structurally unsafe path."""


def _segment_param(segment: str) -> tuple[str | None, bool]:
    """``:name?`` → (name, optional); literal → (None, False)."""
    match = _PARAM_SEGMENT.match(segment)
    if match is None:
        return None, False
    return match.group(1), match.group(3) == "?"


@dataclass(frozen=True)
class MatchCandidate:
    """One candidate route (Lumi DTO — stable wire shape)."""

    route_path: str  # concrete template, e.g. "/sspai/matrix"
    namespace: str
    title: str  # upstream route name (bounded, from the snapshot)
    params: dict[str, str]  # values extracted from the xmlUrl path
    missing_params: tuple[str, ...]  # placeholders not derivable
    confidence: str  # "high" | "medium"
    basis: str  # human-readable justification (简体中文)
    ambiguous: bool  # True = same-namespace tie → human must pick
    requires: dict[str, bool | None] | None  # curated credential facts

    @property
    def needs_credentials(self) -> bool:
        """Any curated facet that is affirmatively True."""
        if self.requires is None:
            return False
        return any(value is True for value in self.requires.values())

    def to_dict(self) -> dict[str, object]:
        return {
            "routePath": self.route_path,
            "namespace": self.namespace,
            "title": self.title,
            "params": dict(self.params),
            "missingParams": list(self.missing_params),
            "confidence": self.confidence,
            "basis": self.basis,
            "ambiguous": self.ambiguous,
            "requires": self.requires,
            "needsCredentials": self.needs_credentials,
        }


@dataclass(frozen=True)
class MatchOutcome:
    """Matcher verdict for one OPML entry."""

    kind: str  # "self_rsshub" | "external_rsshub" | "native" | "unknown"
    candidates: tuple[MatchCandidate, ...]
    auto_route_path: str | None  # set only for the single-safe case
    note: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "autoRoutePath": self.auto_route_path,
            "note": self.note,
        }


def instantiate_route(route_path: str, params: dict[str, str]) -> str:
    """Fill a template route path (``/36kr/:category/:subCategory?``)
    with concrete values → the RSSHub path to fetch/subscribe.

    Structural only: every value is percent-encoded per segment, missing
    OPTIONAL segments are dropped, missing REQUIRED parameters raise
    MissingRouteParams, and the result must pass the same shape check as
    ``rsshub.build_path`` (no empty/``.``/``..``/``//`` segments). No
    upstream code or regex is ever executed.
    """
    filled: list[str] = []
    for raw in route_path.strip("/").split("/"):
        if not raw:
            continue
        name, optional = _segment_param(raw)
        if name is None:
            filled.append(raw)
            continue
        value = params.get(name)
        if value is not None and str(value).strip():
            filled.append(quote(str(value), safe=""))
        elif optional:
            continue  # drop the whole optional segment
        else:
            raise MissingRouteParams((name,))
    path = "/" + "/".join(filled)
    if not path.startswith("/") or "//" in path:
        raise UnsafeRoutePath(route_path)
    if any(segment in ("", ".", "..") for segment in path.split("/")[1:]):
        raise UnsafeRoutePath(route_path)
    return path


def _requires_of(namespace: str) -> dict[str, bool | None] | None:
    facets = NAMESPACE_REQUIRES.get(namespace)
    return dict(facets) if facets else None


def _pattern_params(pattern: str) -> tuple[str, ...]:
    """Placeholder names in an upstream pattern (optional included)."""
    return tuple(name for name, _body, _opt in _PARAM_TOKEN.findall(pattern))


def _required_params(pattern: str) -> tuple[str, ...]:
    """Placeholders whose segment is NOT optional (must be derivable)."""
    return tuple(
        name for name, _body, opt in _PARAM_TOKEN.findall(pattern) if opt != "?"
    )


def _route_relative_regex(route: UpstreamRoute) -> re.Pattern[str]:
    """Namespace-relative pattern → anchored matcher (structural only:
    upstream ``{...}`` regex hints collapse to ``[^/]+``; nothing from
    upstream is ever executed)."""
    return _pattern_regex(route.path_pattern)


def _strip_feed_file_path(path: str) -> str:
    """``/feed`` → ``''`` (root feed); real paths stay untouched."""
    clean = path.strip("/")
    if clean.lower() in _FEED_FILE_SUFFIXES:
        return ""
    return "/" + clean


def _literal_segments(pattern: str) -> tuple[str, ...]:
    segments: list[str] = []
    for raw in pattern.strip("/").split("/"):
        if raw and not raw.startswith(":"):
            segments.append(raw)
    return tuple(segments)


def _path_segments(url: str | None) -> tuple[str, ...]:
    if not url:
        return ()
    try:
        parts = urlsplit(url)
    except ValueError:
        return ()
    if parts.scheme not in ("http", "https"):
        return ()
    return tuple(segment for segment in parts.path.strip("/").split("/") if segment)


def classify_feed_url(url: str, instance_origins: tuple[str, ...]) -> tuple[str, bool]:
    """xmlUrl → (kind, rsshub_shaped).

    kind: "self_rsshub" (URL points at the operator's own instance —
    either the BFF-facing or the FreshRSS-facing base), "external"
    (RSSHub-shaped path on some other host), or "native".

    "RSSHub-shaped" is a structural decision: the path's first segment
    is a snapshot namespace and the remainder instantiates one of that
    namespace's upstream patterns. Unknown namespaces never classify as
    RSSHub, so ordinary native feeds are untouched.
    """
    host = host_of(url)
    if host is None:
        return "native", False
    for origin in instance_origins:
        origin_host = host_of(origin)
        if origin_host and host == origin_host:
            return "self_rsshub", True
    try:
        parts = urlsplit(url)
    except ValueError:
        return "native", False
    if match_concrete_path(parts.path):
        return "external", True
    return "native", False


def _native_candidates(
    xml_url: str, html_url: str | None
) -> tuple[tuple[MatchCandidate, ...], bool]:
    """Native feed → candidates via curated domain map + path alignment.

    Returns (candidates, any_ambiguous). Same-namespace ties are demoted
    to medium + ambiguous (same-domain multi-route guard).
    """
    xml_host = host_of(xml_url)
    html_segments = _path_segments(html_url)
    namespaces: list[str] = []
    for namespace in (*namespaces_for_host(xml_host), *namespaces_for_host(host_of(html_url) if html_url else None)):
        if namespace not in namespaces:
            namespaces.append(namespace)
    if not namespaces:
        return (), False

    try:
        xml_path = urlsplit(xml_url).path
    except ValueError:
        xml_path = ""
    informative = _strip_feed_file_path(xml_path)

    scored: list[MatchCandidate] = []
    for namespace in namespaces:
        for route in routes_snapshot().namespaces.get(namespace, ()):
            regex = _route_relative_regex(route)
            found = regex.match(informative) if informative else regex.match("/")
            if found is not None:
                params = {
                    key: value
                    for key, value in found.groupdict().items()
                    if value is not None
                }
            else:
                params = {}
            missing = tuple(
                name for name in _required_params(route.path_pattern) if name not in params
            )
            # Path alignment: literal route segments present in htmlUrl.
            literals = _literal_segments(route.path_pattern)
            alignment = sum(1 for seg in literals if seg in html_segments)
            if found is not None and not missing:
                confidence, basis = (
                    CONFIDENCE_HIGH,
                    f"订阅地址路径可直接对应 RSSHub 路由「{route.path_pattern}」（{route.name or namespace}）",
                )
            elif alignment > 0:
                confidence = CONFIDENCE_MEDIUM
                basis = f"站点页面路径与路由「{route.path_pattern}」（{route.name or namespace}）部分吻合"
            else:
                confidence = CONFIDENCE_MEDIUM
                basis = f"站点域名匹配到 {namespace} 命名空间的路由「{route.name or route.path_pattern}」"
            scored.append(
                MatchCandidate(
                    route_path=f"/{namespace}{route.path_pattern}",
                    namespace=namespace,
                    title=route.name or namespace,
                    params=params,
                    missing_params=missing,
                    confidence=confidence,
                    basis=basis,
                    ambiguous=False,
                    requires=_requires_of(namespace),
                )
            )

    # Same-domain multi-route disambiguation: when MORE THAN ONE route
    # fully explains the xmlUrl path, none of them may win automatically.
    full_explainers = [c for c in scored if c.confidence == CONFIDENCE_HIGH]
    any_ambiguous = len(full_explainers) > 1
    if any_ambiguous:
        scored = [
            (
                MatchCandidate(
                    route_path=c.route_path,
                    namespace=c.namespace,
                    title=c.title,
                    params=c.params,
                    missing_params=c.missing_params,
                    confidence=CONFIDENCE_MEDIUM,
                    basis=c.basis + "；同域存在多条可解释该路径的路由，需人工选择",
                    ambiguous=True,
                    requires=c.requires,
                )
                if c.confidence == CONFIDENCE_HIGH
                else c
            )
            for c in scored
        ]

    # Stability: concrete path matches first, then stronger alignment.
    scored.sort(
        key=lambda c: (
            c.confidence != CONFIDENCE_HIGH,
            c.ambiguous,
            len(c.missing_params),
            -len(_literal_segments(c.route_path.split("/", 2)[-1] or c.route_path)),
            c.route_path,
        )
    )
    return tuple(scored[:20]), any_ambiguous


def match_source(
    xml_url: str,
    html_url: str | None,
    instance_origins: tuple[str, ...],
) -> MatchOutcome:
    """One OPML entry → matcher verdict (pure function, no network).

    ``instance_origins``: origins the operator's own RSSHub is reachable
    at (BFF view + FreshRSS view). An xmlUrl on any of them is already
    the preferred shape (self_rsshub — nothing to replace). External
    RSSHub instances rewrite to the local instance; native feeds go
    through domain + path matching.
    """
    kind, rsshub_shaped = classify_feed_url(xml_url, instance_origins)

    if kind == "self_rsshub":
        return MatchOutcome(
            kind="self_rsshub",
            candidates=(),
            auto_route_path=None,
            note="已是本站 RSSHub 地址，无需替换。",
        )

    if rsshub_shaped:
        try:
            path = urlsplit(xml_url).path
        except ValueError:
            path = ""
        concrete = match_concrete_path(path)
        if concrete:
            route = concrete[0].route
            return MatchOutcome(
                kind="external_rsshub",
                candidates=(
                    MatchCandidate(
                        route_path=path,
                        namespace=route.namespace,
                        title=route.name or route.namespace,
                        params=dict(concrete[0].params),
                        missing_params=(),
                        confidence=CONFIDENCE_HIGH,
                        basis="外部 RSSHub 实例的已知路由，可改用本站实例（替换前会实际验证）。",
                        ambiguous=False,
                        requires=_requires_of(route.namespace),
                    ),
                ),
                auto_route_path=path,
                note=None,
            )
        # Namespace-shaped but unverifiable against the snapshot: do not
        # rewrite blindly — keep the original URL.
        return MatchOutcome(
            kind="unknown",
            candidates=(),
            auto_route_path=None,
            note="外部 RSSHub 风格地址但不在已验证路由清单内，保留原地址。",
        )

    candidates, ambiguous = _native_candidates(xml_url, html_url)
    if not candidates:
        return MatchOutcome(
            kind="unknown",
            candidates=(),
            auto_route_path=None,
            note="站点不在 RSSHub 路由覆盖范围内，保留原生订阅。",
        )
    auto: str | None = None
    note: str | None = None
    high = [c for c in candidates if c.confidence == CONFIDENCE_HIGH]
    if not ambiguous and len(high) == 1:
        only = high[0]
        if only.needs_credentials:
            note = "唯一候选路由需要 RSSHub 实例配置凭据（Cookie / 登录 / 额外服务），不会静默替换。"
        elif only.missing_params:
            note = "唯一候选路由缺少必填参数（{}），需要人工补充。".format(
                ", ".join(only.missing_params)
            )
        else:
            auto = only.route_path
    elif ambiguous:
        note = "同域存在多条可解释该地址的路由，请人工选择。"
    else:
        note = "存在候选路由，但需要人工选择。"
    return MatchOutcome(
        kind="native",
        candidates=candidates,
        auto_route_path=auto,
        note=note,
    )
