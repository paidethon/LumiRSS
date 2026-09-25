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

import re
import time
import urllib.parse
from collections import OrderedDict
from dataclasses import dataclass
from datetime import timedelta

import feedparser
import httpx
from pydantic import ValidationError

from lumirss.adapters.freshrss import AdapterError
from lumirss.config import RssHubSettings
from lumirss.feed_preview import (
    FeedPreview,
    NotAFeedError,
    count_feed_entries,
    parse_feed_document,
    read_bounded_body,
)
from lumirss.http_fetch import follow_redirects, origin_of

__all__ = [
    "CATALOG",
    "FAILURE_AUTH_FAILURE",
    "FAILURE_BAD_CONTENT",
    "FAILURE_NETWORK_ERROR",
    "FAILURE_NO_NEW_CONTENT",
    "FAILURE_NOT_FOUND",
    "FAILURE_RATE_LIMITED",
    "FAILURE_RSSHUB_UNREACHABLE",
    "FAILURE_UPSTREAM_REJECT",
    "NO_NEW_CONTENT_WINDOW",
    "RssHubFetchError",
    "RssHubFavoriteNotFound",
    "RssHubInvalidParameters",
    "RssHubNotConfigured",
    "RssHubParameter",
    "RssHubPreviewCache",
    "RssHubRefreshRateLimited",
    "RssHubRequires",
    "RssHubRoute",
    "RssHubRouteNotFound",
    "RssHubService",
    "build_path",
    "looks_like_rsshub_error_page",
    "match_route_path",
    "requires_json",
]

_MAX_REDIRECTS = 5
_HEADERS = {"User-Agent": "LumiRSS/0.1 (+self-hosted rsshub preview)"}

# N026 稳定失败分类（时间线行 + preview 错误体的 failureClass）。
# 连接/超时到 RSSHub 源站 → rsshub_unreachable；RSSHub 把上游 4xx/5xx
# 或错误页（非 feed 内容）原样吐回来 → upstream_reject；RSSHub 对 Lumi
# 返回 401/403（如 access key 错）→ auth_failure；feed 正常但 0 条目
# 且窗口内曾有内容 → no_new_content。其余沿用 F050 词汇表映射。
FAILURE_RSSHUB_UNREACHABLE = "rsshub_unreachable"
FAILURE_UPSTREAM_REJECT = "upstream_reject"
FAILURE_AUTH_FAILURE = "auth_failure"
FAILURE_NOT_FOUND = "not_found"
FAILURE_RATE_LIMITED = "rate_limited"
FAILURE_NO_NEW_CONTENT = "no_new_content"
FAILURE_BAD_CONTENT = "bad_content"
FAILURE_NETWORK_ERROR = "network_error"

# no_new_content 判定窗口：窗口内存在 entry_count>0 的成功运行才算
# 「曾有内容、现在枯竭」，避免把新路由的首次 0 条目误判为故障。
NO_NEW_CONTENT_WINDOW = timedelta(hours=6)

# RSSHub 错误页特征（200 + HTML 错误页而非 feed）。中英文实例都出现
# 「RSSHub」字样 + 错误词；只在前 2KB 找，避免误伤正常 feed。
_ERROR_PAGE_MARKERS = ("rsshub",)
_ERROR_PAGE_WORDS = ("error", "错误")


class RssHubPreviewCache:
    """N027: per-user in-memory preview cache (TTL + LRU, bounded).

    Keyed by ``(user_id, route_key)`` so accounts never share cached
    previews. TTL is sliding-expiry by stored-at monotonic time; the LRU
    bound evicts the least recently USED entry beyond capacity. Purely
    process-local — a restart is a cold cache, and ``invalidate`` only
    ever drops the ONE route requested (never a global clear).
    """

    def __init__(self, *, ttl_s: float = 300.0, capacity: int = 50) -> None:
        self._ttl_s = ttl_s
        self._capacity = capacity
        self._entries: OrderedDict[tuple[str, str], tuple[float, FeedPreview]] = (
            OrderedDict()
        )

    def get(self, user_id: str, route_key: str) -> tuple[FeedPreview, float] | None:
        """Cache hit → (preview, age_s); expired/missing → None."""
        key = (user_id, route_key)
        entry = self._entries.get(key)
        if entry is None:
            return None
        stored_at, preview = entry
        age_s = time.monotonic() - stored_at
        if age_s >= self._ttl_s:
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return preview, age_s

    def put(self, user_id: str, route_key: str, preview: FeedPreview) -> None:
        self._entries[(user_id, route_key)] = (time.monotonic(), preview)
        self._entries.move_to_end((user_id, route_key))
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)

    def invalidate(self, user_id: str, route_key: str) -> bool:
        """Drop exactly one route's entry; returns whether it existed."""
        key = (user_id, route_key)
        if key in self._entries:
            del self._entries[key]
            return True
        return False


class RssHubNotConfigured(AdapterError):
    """RSSHUB_BASE_URL is missing or invalid in the BFF configuration."""


class RssHubRouteNotFound(AdapterError):
    """The requested route id is not in the Lumi RSSHub catalog."""


class RssHubInvalidParameters(AdapterError):
    """Route parameters are missing, unknown or fail pattern validation."""


class RssHubFavoriteNotFound(AdapterError):
    """N021: the referenced route favorite does not exist for this user."""


class RssHubRefreshRateLimited(AdapterError):
    """N027: the per-user refresh budget (6/min) is exhausted."""

    def __init__(self, retry_after_s: int) -> None:
        super().__init__(
            f"Too many refreshes; retry after {retry_after_s} seconds."
        )
        self.retry_after_s = retry_after_s


class RssHubFetchError(AdapterError):
    """The RSSHub instance could not produce a feed (network/status/timeout).

    N026: ``failure_class`` carries the stable route-context failure
    class; the default keeps historical callers ("network_error")
    working unchanged.
    """

    def __init__(
        self, message: str, *, failure_class: str = FAILURE_NETWORK_ERROR
    ) -> None:
        super().__init__(message)
        self.failure_class = failure_class


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
class RssHubRequires:
    """N023：路由依赖元数据（curated 静态数据）。

    三态字段：True = 需要 / False = 不需要 / None = 未知（诚实呈现，
    绝不把未知冒充为「不需要」）。来源是 Lumi 维护的 curated 知识
    （RSSHub 文档/路由实现的已知事实），随目录条目一起人工维护。"""

    login: bool | None = None
    cookies: bool | None = None
    render: bool | None = None
    extra_service: bool | None = None


def requires_json(route: "RssHubRoute") -> dict[str, bool | None] | None:
    """路由依赖 → wire 形状（未标注的路由 → None，UI 显示「未知」）。"""
    if route.requires is None:
        return None
    return {
        "login": route.requires.login,
        "cookies": route.requires.cookies,
        "render": route.requires.render,
        "extraService": route.requires.extra_service,
    }


@dataclass(frozen=True)
class RssHubRoute:
    """One supported RSSHub route (Lumi-owned, stable contract)."""

    id: str
    title: str
    description: str
    path_template: str  # e.g. "/github/starred_repos/{user}"
    parameters: tuple[RssHubParameter, ...]
    # N023：依赖元数据（None = 未标注 → 依赖未知，诚实呈现）。
    requires: RssHubRequires | None = None


# Lumi-curated catalog. Every entry verified against the pinned local
# RSSHub instance (docker-compose, diygod/rsshub@387fd32) on 2026-09-01:
# each route returned HTTP 200 with a parseable RSS/Atom document.
#
# N023 ``requires`` is curated static knowledge per route (RSSHub route
# implementation / docs facts), NOT runtime probing: True = 该路由需要 /
# False = 不需要 / None = 未知（诚实呈现为「未知」，绝不冒充「不需要」）。
# Partial metadata is intentional — unknown facets stay None.
CATALOG: tuple[RssHubRoute, ...] = (
    RssHubRoute(
        id="ithome-ranking-24h",
        title="IT之家 24 小时热榜",
        description="IT之家 24 小时热门新闻榜。",
        path_template="/ithome/ranking/24h",
        parameters=(),
        requires=RssHubRequires(login=False, cookies=False, render=False, extra_service=False),
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
        requires=RssHubRequires(login=False, cookies=False, render=False, extra_service=False),
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
        # 知乎路由需要配置 ZHIHU_COOKIES 才能稳定出内容（RSSHub 文档已知事实）。
        requires=RssHubRequires(login=None, cookies=True, render=None, extra_service=False),
    ),
    RssHubRoute(
        id="zhihu-daily",
        title="知乎日报",
        description="知乎日报当日精选。",
        path_template="/zhihu/daily",
        parameters=(),
        requires=RssHubRequires(login=False, cookies=False, render=False, extra_service=False),
    ),
    RssHubRoute(
        id="sspai-matrix",
        title="少数派 Matrix",
        description="少数派社区 Matrix 最新文章。",
        path_template="/sspai/matrix",
        parameters=(),
        requires=RssHubRequires(login=False, cookies=False, render=False, extra_service=False),
    ),
    RssHubRoute(
        id="hackernews",
        title="Hacker News",
        description="Hacker News 首页热门。",
        path_template="/hackernews",
        parameters=(),
        requires=RssHubRequires(login=False, cookies=False, render=False, extra_service=False),
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
        # YouTube 路由依赖实例配置的 YouTube Data API key（额外服务）。
        requires=RssHubRequires(login=False, cookies=False, render=False, extra_service=True),
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
        requires=RssHubRequires(login=False, cookies=False, render=False, extra_service=False),
    ),
    RssHubRoute(
        id="cnbeta",
        title="CNBeta",
        description="cnBeta 中文业界资讯。",
        path_template="/cnbeta",
        parameters=(),
        requires=RssHubRequires(login=False, cookies=False, render=False, extra_service=False),
    ),
    RssHubRoute(
        id="huxiu-article",
        title="虎嗅文章",
        description="虎嗅网最新文章。",
        path_template="/huxiu/article",
        parameters=(),
        requires=RssHubRequires(login=False, cookies=False, render=False, extra_service=False),
    ),
    RssHubRoute(
        id="36kr-newsflashes",
        title="36氪快讯",
        description="36氪 7×24 小时快讯。",
        path_template="/36kr/newsflashes",
        parameters=(),
        requires=RssHubRequires(login=False, cookies=False, render=False, extra_service=False),
    ),
    RssHubRoute(
        id="coolapk-hot",
        title="酷安热帖",
        description="酷安社区热门帖子。",
        path_template="/coolapk/hot",
        parameters=(),
        # 酷安需要实例配置凭据生成请求签名（RSSHub 文档已知事实）。
        requires=RssHubRequires(login=None, cookies=True, render=None, extra_service=False),
    ),
    RssHubRoute(
        id="readhub",
        title="Readhub 热门",
        description="Readhub 科技热门话题。",
        path_template="/readhub",
        parameters=(),
        requires=RssHubRequires(login=False, cookies=False, render=False, extra_service=False),
    ),
    RssHubRoute(
        id="douban-book-latest",
        title="豆瓣新书速递",
        description="豆瓣读书新书速递。",
        path_template="/douban/book/latest",
        parameters=(),
        # 豆瓣部分部署需要 Cookie（实例而异）→ cookies 诚实标注未知。
        requires=RssHubRequires(login=False, cookies=None, render=False, extra_service=False),
    ),
)

_CATALOG_BY_ID = {route.id: route for route in CATALOG}


def _template_pattern(template: str) -> tuple[re.Pattern[str], tuple[str, ...]]:
    """Compile one path template to an anchored matcher + placeholder keys."""
    keys = tuple(re.findall(r"\{(\w+)\}", template))
    parts = re.split(r"\{\w+\}", template)
    pattern = "^" + "([^/]+)".join(re.escape(part) for part in parts) + "$"
    return re.compile(pattern), keys


_TEMPLATE_MATCHERS = tuple(
    (route, *_template_pattern(route.path_template)) for route in CATALOG
)


def match_route_path(path: str) -> tuple[RssHubRoute, dict[str, str]] | None:
    """Match an absolute feed URL path against the Lumi catalog.

    Returns (route, decoded params) when the path instantiates a known
    template — used server-side to attribute a generic subscription to
    its RSSHub route (N021/N025 recording) without trusting any client
    supplied route id. Unknown paths → None.
    """
    for route, pattern, keys in _TEMPLATE_MATCHERS:
        matched = pattern.match(path)
        if matched:
            params = {
                key: urllib.parse.unquote(group)
                for key, group in zip(keys, matched.groups(), strict=True)
            }
            return route, params
    return None


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

    async def fetch_document(self, path: str) -> bytes:
        """Bounded in-origin fetch of one RSSHub path (N024 diff sides).

        Same origin-locked boundary as preview; the path is appended to
        the OPERATOR-CONFIGURED base. Raises RssHubFetchError — callers
        that diff two sides catch per side and report honestly."""
        settings = self.load_settings()
        body, _final_url = await self._fetch_feed(settings.RSSHUB_BASE_URL, path)
        return body

    async def preview(
        self,
        route_id: str,
        params: dict[str, str],
        *,
        base_override: str | None = None,
    ) -> FeedPreview:
        """Construct + fetch + parse the generated feed (non-mutating).

        Returns the same shape as FeedPreviewService.preview, with
        ``feed_url`` being the FreshRSS-facing subscription URL (built
        from RSSHUB_FRESHRSS_BASE_URL — FreshRSS fetches the feed, not
        the BFF).

        ``base_override`` is E2E-only (see routers/rsshub.py): it swaps
        the base the BFF itself dials so a test can pin a dead endpoint
        and assert the stable error class. It NEVER changes the returned
        subscription URL — that stays built from the configured
        RSSHUB_FRESHRSS_BASE_URL.
        """
        settings = self.load_settings()
        route = _CATALOG_BY_ID.get(route_id)
        if route is None:
            raise RssHubRouteNotFound(
                f"Unknown RSSHub route '{route_id}'."
            )
        path = build_path(route, params)
        base = base_override if base_override else settings.RSSHUB_BASE_URL
        body, _final_url = await self._fetch_feed(base, path)
        try:
            title, site_url, description, feed_format = parse_feed_document(body)
        except NotAFeedError:
            # N026: a 200 HTML error page ("RSSHub 内部错误" etc.) is an
            # upstream rejection — a different failure than random garbage.
            if looks_like_rsshub_error_page(body):
                raise RssHubFetchError(
                    "RSSHub returned an error page instead of a feed.",
                    failure_class=FAILURE_UPSTREAM_REJECT,
                ) from None
            raise
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
            # N025: route timeline keeps a per-run entry count.
            entry_count=count_feed_entries(body),
        )

    async def _fetch_feed(
        self, base_url: str, path: str
    ) -> tuple[bytes, str]:
        """Bounded fetch of base_url + path; redirects stay in-origin.

        The base origin is operator-configured infrastructure, so no
        public-IP validation applies here (it may be a loopback/Docker
        address). What MUST hold: every hop stays on exactly that origin.
        """
        base_origin = origin_of(base_url)

        async def validate_hop(hop_url: str) -> None:
            if origin_of(hop_url) != base_origin.lower():
                raise RssHubFetchError(
                    "RSSHub redirected outside its configured origin."
                )

        def fail(event: str) -> Exception:
            if event == "no_location":
                return RssHubFetchError(
                    "RSSHub redirected without a target location."
                )
            return RssHubFetchError("RSSHub redirected too many times.")

        response, final_url = await follow_redirects(
            base_origin + path,
            send=self._send,
            validate_hop=validate_hop,
            fail=fail,
            max_redirects=_MAX_REDIRECTS,
        )
        try:
            if response.status_code != 200:
                # N026：按路由语境分辨 RSSHub 的拒绝方式，而非全部坍缩成
                # network_error。401/403 是「我们访问 RSSHub」的鉴权问题。
                status = response.status_code
                if status in (401, 403):
                    raise RssHubFetchError(
                        f"RSSHub answered HTTP {status}.",
                        failure_class=FAILURE_AUTH_FAILURE,
                    )
                if status in (404, 410):
                    raise RssHubFetchError(
                        f"RSSHub answered HTTP {status}.",
                        failure_class=FAILURE_NOT_FOUND,
                    )
                if status == 429:
                    raise RssHubFetchError(
                        f"RSSHub answered HTTP {status}.",
                        failure_class=FAILURE_RATE_LIMITED,
                    )
                raise RssHubFetchError(
                    f"RSSHub answered HTTP {status}.",
                    failure_class=FAILURE_UPSTREAM_REJECT,
                )
            return await read_bounded_body(response), final_url
        finally:
            await response.aclose()

    async def _send(self, url: str) -> httpx.Response:
        request = self._client.build_request("GET", url, headers=_HEADERS)
        try:
            return await self._client.send(request, stream=True)
        except httpx.HTTPError as exc:
            # N026: connect/timeout to the RSSHub origin — distinct from
            # upstream rejections so the timeline never collapses them.
            raise RssHubFetchError(
                "The RSSHub instance could not be reached.",
                failure_class=FAILURE_RSSHUB_UNREACHABLE,
            ) from exc


def looks_like_rsshub_error_page(body: bytes) -> bool:
    """N026: RSSHub answers 200 with an HTML error page (not a feed).

    Bounded sniff of the first 2KB: the RSSHub mention plus an error
    word. Real feeds whose title happens to mention RSSHub AND an error
    word in the first 2KB are vanishingly rare; parse_feed_document
    stays the authority on feed-ness — this only upgrades the CLASS.
    """
    head = body[:2048].decode("utf-8", errors="ignore").lower()
    return any(marker in head for marker in _ERROR_PAGE_MARKERS) and any(
        word in head for word in _ERROR_PAGE_WORDS
    )


# ---- N024 路由变更差异预览（标题级 diff；严格只读） -------------------------

# diff 列表边界（预览是对照用途，不是全文搬运；诚实有界）。
DIFF_TITLE_LIMIT = 50

ZERO_ENTRY_HINT = (
    "本次预览返回 0 条目：该路由的依赖（登录 / Cookie / 浏览器渲染 / "
    "额外服务）可能未满足——请先检查 RSSHub 实例配置，这不是健康状态。"
)


def extract_entry_titles(body: bytes) -> list[str]:
    """Bounded offline title extraction for the params diff.

    Parse failures count as no titles (the diff side carries the real
    signal via its own error/entryCount fields); titles are whitespace-
    collapsed and capped at DIFF_TITLE_LIMIT.
    """
    try:
        parsed = feedparser.parse(body)
    except Exception:  # noqa: BLE001 — diff 是辅助对照，解析失败如实为空
        return []
    titles: list[str] = []
    for entry in parsed.entries or []:
        title = entry.get("title")
        if isinstance(title, str) and title.strip():
            titles.append(" ".join(title.split()))
    return titles[:DIFF_TITLE_LIMIT]


def diff_title_sets(
    old_titles: list[str], new_titles: list[str]
) -> dict[str, list[str]]:
    """标题集合 diff（added = 仅新 / removed = 仅旧 / duplicates = 两侧都有）。

    标题是对照键（entry id 不跨参数稳定）；页内重复标题先按首现去重，
    保持稳定顺序。列表各自有界（DIFF_TITLE_LIMIT）。"""
    old_set = set(old_titles)
    new_set = set(new_titles)
    return {
        "added": list(dict.fromkeys(t for t in new_titles if t not in old_set)),
        "removed": list(dict.fromkeys(t for t in old_titles if t not in new_set)),
        "duplicates": list(dict.fromkeys(t for t in new_titles if t in old_set)),
    }


def safe_rsshub_path(path: str) -> bool:
    """Structural check for a client-supplied RSSHub path (N024 old URL).

    Same rules as build_path's post-check: must start with '/', no empty
    / ``.`` / ``..`` segments. The path is appended to the OPERATOR-
    CONFIGURED base (origin-locked fetch), so this is a shape check, not
    an SSRF boundary."""
    if not path.startswith("/") or "//" in path:
        return False
    return all(segment not in ("", ".", "..") for segment in path.split("/")[1:])
