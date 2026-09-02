"""RSSHub source discovery — 0014: Lumi-owned route catalog + preview.

RSSHub is an upstream FEED GENERATOR: Lumi builds a route URL server-side,
previews the generated RSS/Atom feed through the BFF, and hands the feed
URL to FreshRSS on subscribe (0013 pipeline). RSSHub is never a Lumi data
backend and the browser never calls RSSHub directly.

Catalog: a small Lumi-curated set of route descriptors (NOT the full
RSSHub route set, NOT scraped from RSSHub docs at runtime). Each entry
carries enough metadata to render a parameter form and to construct a
valid path safely:

- ``id``: stable Lumi identifier (kebab-case);
- ``pathTemplate``: RSSHub path with ``{key}`` placeholders;
- ``parameters``: key/label/required/regex pattern/example/help.

Construction (``build_path``) is server-side and strict: every value must
full-match the route's pattern, then gets URL-encoded per path segment;
the final path is structurally checked (no empty/``..``/``//`` segments).
A validated pattern + segment encoding + structural check together make
path injection impossible.

Preview fetches ``RSSHUB_BASE_URL + path`` (operator-configured server
infrastructure — NOT user input, may be internal/loopback), bounded body,
bounded redirects that must stay inside the configured origin. The
returned ``feedUrl`` is built from ``RSSHUB_FRESHRSS_BASE_URL`` because
FreshRSS (not the BFF) fetches the feed after subscribe — 0008 verified
the host view (127.0.0.1:1200) differs from the container view
(http://rsshub:1200).
"""

from dataclasses import dataclass
import re
import urllib.parse

import httpx
from pydantic import ValidationError

from lumirss.adapters.freshrss import AdapterError
from lumirss.config import RssHubSettings
from lumirss.feed_preview import (
    FeedPreview,
    parse_feed_document,
    read_bounded_body,
)

__all__ = [
    "CATALOG",
    "RssHubFetchError",
    "RssHubInvalidParameters",
    "RssHubNotConfigured",
    "RssHubParameter",
    "RssHubRoute",
    "RssHubRouteNotFound",
    "RssHubService",
    "build_path",
]

_MAX_REDIRECTS = 5
_HEADERS = {"User-Agent": "LumiRSS/0.1 (+self-hosted rsshub preview)"}


class RssHubNotConfigured(AdapterError):
    """RSSHUB_BASE_URL is missing or invalid in the BFF configuration."""


class RssHubRouteNotFound(AdapterError):
    """The requested route id is not in the Lumi RSSHub catalog."""


class RssHubInvalidParameters(AdapterError):
    """Route parameters are missing, unknown or fail pattern validation."""


class RssHubFetchError(AdapterError):
    """The RSSHub instance could not produce a feed (network/status/timeout)."""


@dataclass(frozen=True)
class RssHubParameter:
    """One route parameter descriptor (Lumi DTO, form-renderable)."""

    key: str
    label: str
    required: bool
    pattern: str  # regex the value must FULL match (validated server-side)
    example: str
    help: str


@dataclass(frozen=True)
class RssHubRoute:
    """One supported RSSHub route (Lumi-owned, stable contract)."""

    id: str
    title: str
    description: str
    path_template: str  # e.g. "/github/starred_repos/{user}"
    parameters: tuple[RssHubParameter, ...]


# Lumi-curated catalog. Every entry verified against the pinned local
# RSSHub instance (docker-compose, diygod/rsshub@387fd32) on 2026-09-01:
# each route returned HTTP 200 with a parseable RSS/Atom document.
CATALOG: tuple[RssHubRoute, ...] = (
    RssHubRoute(
        id="ithome-ranking-24h",
        title="IT之家 24 小时热榜",
        description="IT之家 24 小时热门新闻榜。",
        path_template="/ithome/ranking/24h",
        parameters=(),
    ),
    RssHubRoute(
        id="github-starred-repos",
        title="GitHub 用户星标仓库",
        description="某位 GitHub 用户 star 过的仓库动态。",
        path_template="/github/starred_repos/{user}",
        parameters=(
            RssHubParameter(
                key="user",
                label="GitHub 用户名",
                required=True,
                pattern=r"^[a-zA-Z0-9-]{1,39}$",
                example="DIYgod",
                help="GitHub 用户名（字母 / 数字 / 连字符）。",
            ),
        ),
    ),
    RssHubRoute(
        id="zhihu-people-activities",
        title="知乎用户动态",
        description="知乎用户主页的动态（回答 / 想法 / 关注等）。",
        path_template="/zhihu/people/activities/{id}",
        parameters=(
            RssHubParameter(
                key="id",
                label="知乎用户 ID",
                required=True,
                pattern=r"^[a-zA-Z0-9_.-]{1,64}$",
                example="zhang-jia-wei",
                help="知乎主页 URL 末尾的用户 ID（如 zhang-jia-wei）。",
            ),
        ),
    ),
    RssHubRoute(
        id="zhihu-daily",
        title="知乎日报",
        description="知乎日报当日精选。",
        path_template="/zhihu/daily",
        parameters=(),
    ),
    RssHubRoute(
        id="sspai-matrix",
        title="少数派 Matrix",
        description="少数派社区 Matrix 最新文章。",
        path_template="/sspai/matrix",
        parameters=(),
    ),
    RssHubRoute(
        id="hackernews",
        title="Hacker News",
        description="Hacker News 首页热门。",
        path_template="/hackernews",
        parameters=(),
    ),
    RssHubRoute(
        id="youtube-channel",
        title="YouTube 频道",
        description="YouTube 频道的视频更新。",
        path_template="/youtube/channel/{id}",
        parameters=(
            RssHubParameter(
                key="id",
                label="频道 ID",
                required=True,
                pattern=r"^[a-zA-Z0-9_-]{1,64}$",
                example="UCsXVk37bltHxD1rDPwtNM8Q",
                help="频道 URL 中的 channel ID（UC 开头）。",
            ),
        ),
    ),
    RssHubRoute(
        id="v2ex-topics",
        title="V2EX 主题",
        description="V2EX 社区主题列表。",
        path_template="/v2ex/topics/{type}",
        parameters=(
            RssHubParameter(
                key="type",
                label="列表类型",
                required=True,
                pattern=r"^(hot|latest)$",
                example="hot",
                help="hot = 最热；latest = 最新。",
            ),
        ),
    ),
    RssHubRoute(
        id="cnbeta",
        title="CNBeta",
        description="cnBeta 中文业界资讯。",
        path_template="/cnbeta",
        parameters=(),
    ),
    RssHubRoute(
        id="huxiu-article",
        title="虎嗅文章",
        description="虎嗅网最新文章。",
        path_template="/huxiu/article",
        parameters=(),
    ),
    RssHubRoute(
        id="36kr-newsflashes",
        title="36氪快讯",
        description="36氪 7×24 小时快讯。",
        path_template="/36kr/newsflashes",
        parameters=(),
    ),
    RssHubRoute(
        id="coolapk-hot",
        title="酷安热帖",
        description="酷安社区热门帖子。",
        path_template="/coolapk/hot",
        parameters=(),
    ),
    RssHubRoute(
        id="readhub",
        title="Readhub 热门",
        description="Readhub 科技热门话题。",
        path_template="/readhub",
        parameters=(),
    ),
    RssHubRoute(
        id="douban-book-latest",
        title="豆瓣新书速递",
        description="豆瓣读书新书速递。",
        path_template="/douban/book/latest",
        parameters=(),
    ),
)

_CATALOG_BY_ID = {route.id: route for route in CATALOG}


def _quote_segment(value: str) -> str:
    """URL-encode one path segment (RFC 3986, '/' escaped too)."""
    return urllib.parse.quote(value, safe="")


def build_path(route: RssHubRoute, params: dict[str, str]) -> str:
    """Construct the RSSHub path from validated parameters.

    Raises RssHubInvalidParameters for missing / unknown keys, empty
    values, pattern failures or a structurally unsafe result.
    """
    unknown = sorted(set(params) - {p.key for p in route.parameters})
    if unknown:
        raise RssHubInvalidParameters(
            f"Unknown RSSHub route parameter(s): {', '.join(unknown)}."
        )
    values: dict[str, str] = {}
    for parameter in route.parameters:
        value = params.get(parameter.key)
        if not isinstance(value, str) or not value.strip():
            raise RssHubInvalidParameters(
                f"Missing RSSHub route parameter '{parameter.key}'."
            )
        if not re.fullmatch(parameter.pattern, value):
            raise RssHubInvalidParameters(
                f"RSSHub route parameter '{parameter.key}' is invalid."
            )
        values[parameter.key] = _quote_segment(value)

    path = route.path_template.format(**values)
    if not path.startswith("/") or "//" in path:
        raise RssHubInvalidParameters("RSSHub route produced an unsafe path.")
    segments = path.split("/")
    if any(segment in ("", ".", "..") for segment in segments[1:]):
        raise RssHubInvalidParameters("RSSHub route produced an unsafe path.")
    return path


class RssHubService:
    """Catalog access + bounded preview over the shared HTTP client.

    ``control`` (FreshRSSControlAdapter) is used READ-ONLY for the
    alreadySubscribed check — preview never mutates subscription state.
    """

    def __init__(self, client: httpx.AsyncClient, control) -> None:
        self._client = client
        self._control = control

    def load_settings(self) -> RssHubSettings:
        """Read RSSHub settings; missing/invalid → RssHubNotConfigured."""
        try:
            settings = RssHubSettings()
        except ValidationError as exc:
            raise RssHubNotConfigured(
                "RSSHub settings are missing or invalid. "
                "Set RSSHUB_BASE_URL (optionally RSSHUB_FRESHRSS_BASE_URL)."
            ) from exc
        if not settings.RSSHUB_BASE_URL:
            raise RssHubNotConfigured(
                "RSSHub is not configured. Set RSSHUB_BASE_URL server-side."
            )
        return settings

    def list_routes(self) -> list[RssHubRoute]:
        return list(CATALOG)

    async def preview(
        self, route_id: str, params: dict[str, str]
    ) -> FeedPreview:
        """Construct + fetch + parse the generated feed (non-mutating).

        Returns the same shape as FeedPreviewService.preview, with
        ``feed_url`` being the FreshRSS-facing subscription URL (built
        from RSSHUB_FRESHRSS_BASE_URL — FreshRSS fetches the feed, not
        the BFF).
        """
        settings = self.load_settings()
        route = _CATALOG_BY_ID.get(route_id)
        if route is None:
            raise RssHubRouteNotFound(
                f"Unknown RSSHub route '{route_id}'."
            )
        path = build_path(route, params)
        base = settings.RSSHUB_BASE_URL
        body, _final_url = await self._fetch_feed(base, path)
        title, site_url, description, feed_format = parse_feed_document(body)
        subscription_url = f"{settings.freshrss_base_url}{path}"
        existing = await self._control.list_subscriptions()
        already_subscribed = any(
            s.feed_url == subscription_url for s in existing
        )
        return FeedPreview(
            title=title,
            feed_url=subscription_url,
            site_url=site_url,
            description=description,
            format=feed_format,
            already_subscribed=already_subscribed,
        )

    async def _fetch_feed(
        self, base_url: str, path: str
    ) -> tuple[bytes, str]:
        """Bounded fetch of base_url + path; redirects stay in-origin.

        The base origin is operator-configured infrastructure, so no
        public-IP validation applies here (it may be a loopback/Docker
        address). What MUST hold: every hop stays on exactly that origin.
        """
        base = urllib.parse.urlsplit(base_url)
        base_origin = urllib.parse.urlunsplit((base.scheme, base.netloc, "", "", ""))
        current = base_origin + path
        for _hop in range(_MAX_REDIRECTS + 1):
            parts = urllib.parse.urlsplit(current)
            origin = urllib.parse.urlunsplit(
                (parts.scheme.lower(), parts.netloc.lower(), "", "", "")
            )
            if origin != base_origin.lower():
                raise RssHubFetchError(
                    "RSSHub redirected outside its configured origin."
                )
            response = await self._send(current)
            try:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        raise RssHubFetchError(
                            "RSSHub redirected without a target location."
                        )
                    current = urllib.parse.urljoin(current, location)
                    continue
                if response.status_code != 200:
                    raise RssHubFetchError(
                        f"RSSHub answered HTTP {response.status_code}."
                    )
                return await read_bounded_body(response), current
            finally:
                await response.aclose()
        raise RssHubFetchError("RSSHub redirected too many times.")

    async def _send(self, url: str) -> httpx.Response:
        request = self._client.build_request("GET", url, headers=_HEADERS)
        try:
            return await self._client.send(request, stream=True)
        except httpx.HTTPError as exc:
            raise RssHubFetchError(
                "The RSSHub instance could not be reached."
            ) from exc
