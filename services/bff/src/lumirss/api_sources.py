"""API Sources v1 (phase2 M3): JSON API → JMESPath → Lumi Atom → FreshRSS.

The single pipeline for non-RSS JSON APIs. Lumi owns ONLY the connector
config (api_sources) and regenerates the Atom feed on demand; converted
entries live exclusively in FreshRSS — never in a Lumi content table.

Guardrails (03-report §13/§14):
- endpoint: https-only structural check + full SSRF baseline (same
  validate_hop as clips) at fetch time; JSON content-type required;
  response capped at 2MB.
- JMESPath expressions: length-capped, compiled once, no eval surface;
  items result capped (100) and per-item strings truncated.
- Atom: rendered via the shared RFC 4287 renderer (atom_render) with
  stdlib escaping; entry IDs are stable (deterministic from the mapped
  id field + source uuid); feed updated is content-derived, persisted
  and monotonic; ETag/304 are therefore stable across fetches.
- Last-known-good: every successful fetch persists the rendered Atom
  (migration 0019); upstream failures serve it stale (X-Lumi-Stale: 1)
  and only a source with no last-good body gets the 502 stub.
- Feed URL carries a per-source high-entropy secret compared in constant
  time (it is the credential — the endpoint lives OUTSIDE /api/* so the
  browser middlewares don't apply, FreshRSS dials it directly).
"""

import hashlib
import json
import secrets as _secrets
import urllib.parse
from dataclasses import dataclass
from typing import Any

import httpx
import jmespath

from lumirss.atom_render import AtomEntry, newest_rfc3339, render_feed, rfc3339
from lumirss.clip_fetch import (
    ClipFetchError,
    ClipForbidden,
    validate_hop,
)
from lumirss.util import constant_time_equals, utc_now

_MAX_JSON_BYTES = 2 * 1024 * 1024
_FETCH_TIMEOUT_SECONDS = 20.0
_MAX_ITEMS = 100
_MAX_EXPR_LENGTH = 500
_MAX_FIELD_EXPR_LENGTH = 200
_FIELD_KEYS = ("id", "title", "url", "published", "body")
_MAX_FIELD_LENGTH = 8000
_PREVIEW_ITEMS = 5

_ALLOWED_ITEM_KEYS = frozenset(_FIELD_KEYS)


class ApiSourceInvalid(ValueError):
    """Config payload failed validation."""


class ApiSourceNotFound(Exception):
    """No such source."""


class ApiSourceFetchFailed(Exception):
    """The configured endpoint could not be fetched/parsed."""


class ApiSourceRateLimited(ApiSourceFetchFailed):
    """The upstream answered HTTP 429 (N129).

    Carries the upstream ``Retry-After`` hint (seconds when parseable,
    else None) so the fetch path can persist ``next_allowed_run`` and
    back off instead of hammering a rate-limited API. The message keeps
    the historical "HTTP 429" shape so the pagination abort path keeps
    classifying it identically."""

    def __init__(self, retry_after_seconds: int | None) -> None:
        super().__init__("API 端点返回 HTTP 429。")
        self.retry_after_seconds = retry_after_seconds


class ApiSourceBudgetExhausted(Exception):
    """N129: the per-source hourly fetch budget is spent (stable 429).

    ``next_allowed_run`` is the honest RFC3339 moment the next token
    refills (or the upstream Retry-After verdict, whichever is later)."""

    def __init__(self, next_allowed_run: str) -> None:
        super().__init__(f"本来源的每小时抓取预算已用完，下次允许运行时间：{next_allowed_run}")
        self.next_allowed_run = next_allowed_run


class ApiSourceExpressionError(Exception):
    """JMESPath expression failed to compile or evaluate."""


class ApiSourcePreviewError(ApiSourceExpressionError):
    """Preview-level expression/pagination failure (F041: mapped 422)."""


@dataclass(frozen=True)
class ApiSourceRecord:
    uuid: str
    name: str
    endpoint: str
    items_expr: str
    field_map: str
    enabled: bool
    secret: str
    etag: str | None
    last_status: str | None
    last_success_at: str | None
    last_error: str | None
    created_at: str
    atom_body: str | None = None
    feed_updated: str | None = None
    pagination: str = '{"mode":"none"}'
    confirmed_schema: str | None = None
    schema_drift: str | None = None
    # N129: per-source fetch budget (hourly token bucket + Retry-After).
    max_runs_per_hour: int = 4
    respect_retry_after: bool = True
    next_allowed_run: str | None = None

    def to_dict(self, *, with_secret: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "uuid": self.uuid,
            "name": self.name,
            "endpoint": self.endpoint,
            "itemsExpr": self.items_expr,
            "fieldMap": json.loads(self.field_map),
            "enabled": self.enabled,
            "lastStatus": self.last_status,
            "lastSuccessAt": self.last_success_at,
            "lastError": self.last_error,
            "createdAt": self.created_at,
        }
        if with_secret:
            payload["secret"] = self.secret
            payload["atomPath"] = atom_path(self.uuid, self.secret)
        return payload


def atom_base(settings=None) -> str:
    """Docker-internal base URL FreshRSS uses to dial Lumi's Atom feeds.

    Dual-base contract (P0-05a): ``LUMIRSS_ATOM_BASE_URL`` is the address
    INSIDE the docker network (compose service name ``bff`` →
    ``http://bff:8000``); browser-facing clients keep using the relative
    ``atomPath`` through Caddy. An empty setting falls back to the compose
    default instead of the historical loopback address, which is
    unreachable from the FreshRSS container.
    """
    if settings is None:
        from lumirss.config import LumiSettings

        settings = LumiSettings()
    value = settings.LUMIRSS_ATOM_BASE_URL.strip()
    return value or "http://bff:8000"


def atom_path(source_uuid: str, secret: str) -> str:
    return f"/feeds/{source_uuid}.{secret}.atom"


def new_source_secret() -> str:
    """High-entropy per-source credential (shown once at creation)."""
    return _secrets.token_hex(16)


def validate_items_expr(expr: str) -> str:
    if not isinstance(expr, str) or not expr.strip():
        raise ApiSourceInvalid("items expression must not be empty.")
    clean = expr.strip()
    if len(clean) > _MAX_EXPR_LENGTH:
        raise ApiSourceInvalid("items expression is too long.")
    try:
        jmespath.compile(clean)
    except Exception as exc:
        raise ApiSourceExpressionError(f"items 表达式无法编译：{exc}") from exc
    return clean


def validate_field_map(field_map: dict[str, str]) -> str:
    if not isinstance(field_map, dict) or not field_map:
        raise ApiSourceInvalid("field map must be a non-empty object.")
    unknown = set(field_map) - _ALLOWED_ITEM_KEYS
    if unknown:
        raise ApiSourceInvalid(
            f"field map has unknown keys: {sorted(unknown)}"
        )
    if "id" not in field_map or "title" not in field_map:
        raise ApiSourceInvalid("field map requires id and title mappings.")
    compiled: dict[str, str] = {}
    for key, expr in field_map.items():
        if not isinstance(expr, str) or not expr.strip():
            raise ApiSourceInvalid(f"field map {key!r} expression is empty.")
        clean = expr.strip()
        if len(clean) > _MAX_FIELD_EXPR_LENGTH:
            raise ApiSourceInvalid(f"field map {key!r} expression is too long.")
        try:
            jmespath.compile(clean)
        except Exception as exc:
            raise ApiSourceExpressionError(
                f"field map {key!r} 表达式无法编译：{exc}"
            ) from exc
        compiled[key] = clean
    return json.dumps(compiled, ensure_ascii=False, separators=(",", ":"))


def validate_endpoint(url: str) -> str:
    parts = urllib.parse.urlsplit(url.strip())
    if not parts.netloc:
        raise ApiSourceInvalid("API endpoint must be an absolute https URL.")
    # https is the production baseline; an operator-allow-listed private
    # hostname (in-network RSSHub, E2E fixtures) may speak plain http.
    from lumirss.feed_preview import hostname_allowlisted

    if (
        parts.scheme != "https"
        and not hostname_allowlisted(parts.hostname)
    ):
        raise ApiSourceInvalid("API endpoint must be an absolute https URL.")
    if len(url) > 2048:
        raise ApiSourceInvalid("API endpoint is too long.")
    return url.strip()


def parse_field_map(raw: str | dict[str, str]) -> dict[str, str]:
    """Accept the stored JSON string OR an in-memory dict (preview path)."""
    if isinstance(raw, dict):
        return raw
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ApiSourceExpressionError("stored field map is not an object.")
    return value


def map_items(payload: Any, items_expr: str, field_map_raw: str) -> list[dict[str, Any]]:
    """JMESPath evaluation with hard result caps; raises on compile errors."""
    try:
        items = jmespath.search(items_expr, payload)
    except Exception as exc:
        raise ApiSourceExpressionError(f"items 表达式求值失败：{exc}") from exc
    if items is None:
        items = []
    if not isinstance(items, list):
        raise ApiSourceExpressionError("items 表达式结果不是数组。")
    field_map = parse_field_map(field_map_raw)
    mapped: list[dict[str, Any]] = []
    for item in items[:_MAX_ITEMS]:
        if not isinstance(item, dict):
            continue
        entry: dict[str, Any] = {}
        for key, expr in field_map.items():
            value = jmespath.search(expr, item)
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            elif value is not None and not isinstance(value, (str, int, float, bool)):
                value = str(value)
            if isinstance(value, str) and len(value) > _MAX_FIELD_LENGTH:
                value = value[:_MAX_FIELD_LENGTH]
            entry[key] = value
        if entry.get("id") and entry.get("title"):
            mapped.append(entry)
    return mapped


def _pinned_client() -> httpx.AsyncClient:
    """Client over the pinned-IP transport (SSRF TOCTOU fix).

    Module-level factory so tests can inject a mock-transport client."""
    from lumirss.ssrf_transport import PinnedAddressTransport

    return httpx.AsyncClient(transport=PinnedAddressTransport(), trust_env=False)


def parse_retry_after(value: str | None) -> int | None:
    """N129: Retry-After header → bounded whole seconds (None = absent or
    unparseable). HTTP-date form is intentionally not decoded into a
    duration here — only delta-seconds is honored, bounded to one hour so
    a hostile upstream cannot pin ``next_allowed_run`` arbitrarily far."""
    if value is None:
        return None
    text = value.strip()
    if not text.isdigit():
        return None
    try:
        seconds = int(text)
    except ValueError:
        return None
    return min(seconds, 3600)


async def fetch_json(
    http_client: httpx.AsyncClient,
    endpoint: str,
    *,
    timeout_seconds: float = _FETCH_TIMEOUT_SECONDS,
) -> Any:
    """SSRF-checked, size-capped (streamed), JSON-only fetch of the endpoint.

    The response body is streamed with a hard cap instead of being read
    whole first (P0-05f): buffering the full body before the size check
    let an oversized endpoint OOM the BFF. The dial goes through the
    pinned-IP transport (P0-03/P0-05): validate_hop's getaddrinfo check
    alone is TOCTOU-racy — DNS may re-resolve between check and connect;
    the transport re-validates and dials the verified address.
    N129: a 429 raises :class:`ApiSourceRateLimited` carrying the parsed
    Retry-After hint; ``timeout_seconds`` lets the credential probe (N130)
    run the same request shape under a tighter bound."""
    await validate_hop(endpoint)
    pinned_client = _pinned_client()
    try:
        request = pinned_client.build_request(
            "GET",
            endpoint,
            headers={"accept": "application/json"},
            timeout=timeout_seconds,
        )
        try:
            response = await pinned_client.send(request, stream=True, follow_redirects=False)
        except httpx.HTTPError as exc:
            raise ApiSourceFetchFailed("API 端点连接失败。") from exc
        try:
            if response.status_code == 429:
                raise ApiSourceRateLimited(
                    parse_retry_after(response.headers.get("retry-after"))
                )
            if response.status_code != 200:
                raise ApiSourceFetchFailed(f"API 端点返回 HTTP {response.status_code}。")
            content_type = response.headers.get("content-type", "").lower()
            if "json" not in content_type:
                raise ApiSourceFetchFailed("API 端点未返回 JSON。")
            body = bytearray()
            try:
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > _MAX_JSON_BYTES:
                        raise ApiSourceFetchFailed("API 响应超过 2MB 上限。")
            except httpx.HTTPError as exc:
                raise ApiSourceFetchFailed("API 响应读取失败。") from exc
        finally:
            await response.aclose()
    finally:
        await pinned_client.aclose()
    try:
        return json.loads(bytes(body).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApiSourceFetchFailed("API 响应不是有效 JSON。") from exc


# -- Atom generation --------------------------------------------------------


def _entry_id(source_uuid: str, item: dict[str, Any]) -> str:
    raw = str(item.get("id"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"urn:lumirss:apisource:{source_uuid}:{digest}"


def compute_feed_updated(
    items: list[dict[str, Any]], prior: str | None, fallback: str
) -> str:
    """Monotonic, content-derived feed timestamp (canonical RFC 3339 UTC).

    Newest entry ``published`` (when it parses), clamped against the
    persisted prior value so ``updated`` never moves backwards when items
    age out. Falls back to the source's creation time — never wall-clock —
    so identical content always renders a byte-identical feed (stable
    ETag, reliable 304)."""
    candidates = [rfc3339(item.get("published")) for item in items]
    candidates.append(rfc3339(prior))
    return newest_rfc3339(candidates) or rfc3339(fallback) or utc_now()


def generate_atom(
    source: ApiSourceRecord,
    items: list[dict[str, Any]],
    feed_updated: str,
    self_base: str,
    max_entries: int = _MAX_ITEMS,
) -> str:
    """RFC 4287 feed via the shared renderer (stable ids, stdlib escaping).

    Entries get a REQUIRED <updated>: the mapped published timestamp when
    valid, else the stable feed fallback. Authorship is satisfied at feed
    level (the source name); rel=self is an absolute IRI under the
    docker-internal base."""
    feed_self = f"{self_base}{atom_path(source.uuid, source.secret)}"
    entries = [
        AtomEntry(
            entry_id=_entry_id(source.uuid, item),
            title=str(item.get("title") or "(无标题)"),
            updated=rfc3339(item.get("published")) or feed_updated,
            link=str(item["url"]) if item.get("url") else None,
            published=rfc3339(item.get("published")),
            content_html=str(item.get("body") or ""),
        )
        for item in items[:max_entries]
    ]
    return render_feed(
        feed_id=f"urn:lumirss:apisource:{source.uuid}",
        title=source.name,
        updated=feed_updated,
        self_href=feed_self,
        entries=entries,
        feed_author=source.name,
    )


def feed_etag(atom_xml: str) -> str:
    return '"' + hashlib.sha256(atom_xml.encode("utf-8")).hexdigest()[:32] + '"'


# -- F041: Atom-form preview (dry-run, zero writes) --------------------------


_PREVIEW_ATOM_LIMIT = 3
_CONTENT_EXCERPT_LENGTH = 200
_PREVIEW_UUID = "preview"


def preview_atom_entries(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """First ≤3 mapped items in their FINAL Atom-rendered shape.

    Uses the exact same id derivation / title fallback / timestamp
    normalization / content pipeline as :func:`generate_atom`, so what
    the operator previews is what FreshRSS will ingest. Returns
    structured dicts (id/title/link/published/contentExcerpt) instead of
    XML — bounded, no writes anywhere."""
    entries: list[dict[str, Any]] = []
    feed_updated = newest_rfc3339(
        [rfc3339(item.get("published")) for item in items[:_PREVIEW_ATOM_LIMIT]]
    ) or utc_now()
    for item in items[:_PREVIEW_ATOM_LIMIT]:
        body = str(item.get("body") or "")
        entries.append(
            {
                "id": _entry_id(_PREVIEW_UUID, item),
                "title": str(item.get("title") or "(无标题)"),
                "link": str(item["url"]) if item.get("url") else None,
                "published": rfc3339(item.get("published")),
                "updated": rfc3339(item.get("published")) or feed_updated,
                "contentExcerpt": body[:_CONTENT_EXCERPT_LENGTH],
            }
        )
    return entries


# -- F042: pagination sampling -----------------------------------------------


_MAX_PAGES = 50
_MAX_PAGINATED_ITEMS = 1000
_DEFAULT_MAX_PAGES = 5
_DEFAULT_MAX_ITEMS = 200
_PAGE_QUERY_WINDOW = 100  # abort when a page URL grows absurdly


class PaginationInvalid(ApiSourceInvalid):
    """pagination config failed validation."""


def validate_pagination(raw: Any) -> str:
    """Validate + canonicalize the pagination config to a JSON string.

    mode none (default): single fetch, other keys ignored. page: requires
    ``page_param``. cursor: requires ``cursor_path`` (a bounded JMESPath
    expression evaluated against each page payload). max_pages ≤ 50,
    max_items ≤ 1000 — the walk is always bounded."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise PaginationInvalid("pagination must be an object.")
    mode = raw.get("mode", "none")
    if mode not in ("none", "page", "cursor"):
        raise PaginationInvalid("pagination.mode must be none|page|cursor.")
    clean: dict[str, Any] = {"mode": mode}
    if mode == "page":
        page_param = raw.get("page_param")
        if not isinstance(page_param, str) or not page_param.strip():
            raise PaginationInvalid("page 模式需要 page_param。")
        clean["page_param"] = page_param.strip()[:64]
        first_page = raw.get("first_page", 1)
        if not isinstance(first_page, int) or isinstance(first_page, bool) or first_page < 1:
            raise PaginationInvalid("first_page must be a positive integer.")
        clean["first_page"] = min(first_page, 10_000)
    if mode == "cursor":
        cursor_path = raw.get("cursor_path")
        if not isinstance(cursor_path, str) or not cursor_path.strip():
            raise PaginationInvalid("cursor 模式需要 cursor_path。")
        clean["cursor_path"] = validate_field_expr(cursor_path)
    max_pages = raw.get("max_pages", _DEFAULT_MAX_PAGES)
    if not isinstance(max_pages, int) or isinstance(max_pages, bool) or not (1 <= max_pages <= _MAX_PAGES):
        raise PaginationInvalid(f"max_pages must be within 1..{_MAX_PAGES}.")
    clean["max_pages"] = max_pages
    max_items = raw.get("max_items", _DEFAULT_MAX_ITEMS)
    if not isinstance(max_items, int) or isinstance(max_items, bool) or not (1 <= max_items <= _MAX_PAGINATED_ITEMS):
        raise PaginationInvalid(f"max_items must be within 1..{_MAX_PAGINATED_ITEMS}.")
    clean["max_items"] = max_items
    return json.dumps(clean, ensure_ascii=False, separators=(",", ":"))


def validate_field_expr(expr: str) -> str:
    """A bounded JMESPath expression (cursor_path / per-field use)."""
    clean = expr.strip()
    if len(clean) > _MAX_FIELD_EXPR_LENGTH:
        raise PaginationInvalid("cursor_path expression is too long.")
    try:
        jmespath.compile(clean)
    except Exception as exc:
        raise PaginationInvalid(f"cursor_path 表达式无法编译：{exc}") from exc
    return clean


def parse_pagination(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        value = {}
    return value if isinstance(value, dict) else {}


def _url_with_param(endpoint: str, key: str, value: str) -> str:
    parts = urllib.parse.urlsplit(endpoint)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query = [(k, v) for k, v in query if k != key]
    query.append((key, value))
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), parts.fragment)
    )


async def fetch_json_pages(
    http_client: httpx.AsyncClient,
    endpoint: str,
    pagination_raw: str | None,
    items_expr: str,
) -> tuple[list[Any], str]:
    """Walk the configured pagination and return (page payloads, stop_reason).

    Normal stops (published for the run): empty_page / cursor_missing /
    cursor_repeat / max_pages / max_items. HARD failures (atomic: the
    whole run aborts with :class:`ApiSourceFetchFailed`, nothing is
    published): HTTP 429, timeouts, network errors, oversized bodies —
    the caller keeps the last-known-good feed. Every page URL passes the
    same SSRF validation as the base endpoint (cursor mode dials
    cursor-carrying URLs through the identical checked fetch)."""
    config = parse_pagination(pagination_raw)
    mode = config.get("mode", "none")
    if mode == "none":
        return [await fetch_json(http_client, endpoint)], "single"
    max_pages = int(config.get("max_pages", _DEFAULT_MAX_PAGES))
    max_items = int(config.get("max_items", _DEFAULT_MAX_ITEMS))
    # Items-per-page estimate for the max_items bound: count via the
    # items expression when it resolves to a list, else count 1 per page.
    async def page_items(payload: Any) -> int:
        try:
            result = jmespath.search(items_expr, payload)
        except Exception:
            return 1
        return len(result) if isinstance(result, list) else 1

    payloads: list[Any] = []
    if mode == "page":
        page_param = str(config.get("page_param", "page"))
        first_page = int(config.get("first_page", 1))
        total = 0
        for offset in range(max_pages):
            page_number = first_page + offset
            target = _url_with_param(endpoint, page_param, str(page_number))
            if len(target) > 2048 + _PAGE_QUERY_WINDOW:
                return payloads, "max_pages"
            try:
                payload = await fetch_json(http_client, target)
            except ApiSourceRateLimited:
                raise
            except ApiSourceFetchFailed as exc:
                if "HTTP 429" in str(exc):
                    raise ApiSourceFetchFailed(f"分页在第 {page_number} 页被限流（HTTP 429），本次未发布任何条目。") from exc
                raise
            items_here = await page_items(payload)
            if items_here == 0:
                return payloads, "empty_page"
            payloads.append(payload)
            total += items_here
            if total >= max_items:
                return payloads, "max_items"
        return payloads, "max_pages"
    # cursor mode
    cursor_path = str(config.get("cursor_path", ""))
    seen: list[str] = []
    target = endpoint
    total = 0
    for _ in range(max_pages):
        try:
            payload = await fetch_json(http_client, target)
        except ApiSourceRateLimited:
            raise
        except ApiSourceFetchFailed as exc:
            if "HTTP 429" in str(exc):
                raise ApiSourceFetchFailed("分页被限流（HTTP 429），本次未发布任何条目。") from exc
            raise
        payloads.append(payload)
        total += await page_items(payload)
        if total >= max_items:
            return payloads, "max_items"
        try:
            cursor = jmespath.search(cursor_path, payload)
        except Exception:
            cursor = None
        if cursor is None or (isinstance(cursor, str) and not cursor.strip()):
            return payloads, "cursor_missing"
        cursor_text = str(cursor)
        if cursor_text in seen:
            return payloads, "cursor_repeat"
        seen.append(cursor_text)
        target = _url_with_param(endpoint, "cursor", cursor_text)
        if len(target) > 2048 + _PAGE_QUERY_WINDOW:
            return payloads, "max_pages"
    return payloads, "max_pages"


# -- F043: structure baseline + drift ----------------------------------------

_MAX_BASELINE_FIELDS = 64
_MAX_BASELINE_BYTES = 2048
_SCHEMA_SAMPLE_ITEMS = 50


def _schema_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return "json"


def observe_schema(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Observed field schema from a bounded sample of mapped items.

    field → {"type": observed type, "required": present-and-non-null in
    EVERY sampled item}. Bounded to the first _SCHEMA_SAMPLE_ITEMS items
    and _MAX_BASELINE_FIELDS fields (deterministic field order)."""
    sample = items[:_SCHEMA_SAMPLE_ITEMS]
    fields: dict[str, dict[str, Any]] = {}
    for item in sample:
        if not isinstance(item, dict):
            continue
        for key, value in item.items():
            slot = fields.setdefault(key, {"types": set(), "count": 0, "nonnull": 0})
            slot["count"] += 1
            if value is not None:
                slot["types"].add(_schema_type(value))
                slot["nonnull"] += 1
    observed: dict[str, dict[str, Any]] = {}
    for key in sorted(fields)[:_MAX_BASELINE_FIELDS]:
        slot = fields[key]
        types = slot["types"] or {"null"}
        observed[key] = {
            "type": sorted(types)[0] if len(types) == 1 else "mixed",
            "required": slot["count"] > 0 and slot["nonnull"] == slot["count"] == len(sample),
        }
    return observed


def serialize_baseline(schema: dict[str, dict[str, Any]]) -> str | None:
    """Deterministic, size-bounded baseline JSON (None → not storable)."""
    if not schema:
        return None
    trimmed = dict(sorted(schema.items())[:_MAX_BASELINE_FIELDS])
    payload = json.dumps(trimmed, ensure_ascii=False, separators=(",", ":"))
    while len(payload.encode("utf-8")) > _MAX_BASELINE_BYTES and trimmed:
        trimmed.pop(next(iter(trimmed)))
        payload = json.dumps(trimmed, ensure_ascii=False, separators=(",", ":"))
    return payload or None


def diff_schema(
    baseline_raw: str | None, observed: dict[str, dict[str, Any]]
) -> dict[str, list[str]] | None:
    """Baseline vs observed drift. missing/type_changed warn; new_optional
    is advisory only. None when there is no baseline to compare against."""
    if not baseline_raw:
        return None
    try:
        baseline = json.loads(baseline_raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(baseline, dict) or not baseline:
        return None
    missing: list[str] = []
    type_changed: list[str] = []
    new_optional: list[str] = []
    for field, spec in baseline.items():
        expect_type = str(spec.get("type", "")) if isinstance(spec, dict) else ""
        expect_required = bool(spec.get("required")) if isinstance(spec, dict) else False
        current = observed.get(field)
        if current is None or current["type"] == "null":
            # 字段消失，或样本中恒为 null：对必需字段等同缺失。
            if expect_required:
                missing.append(field)
            continue
        if expect_type and current["type"] not in (expect_type, "mixed"):
            type_changed.append(field)
    for field in observed:
        if field not in baseline:
            new_optional.append(field)
    return {
        "missing": sorted(missing),
        "type_changed": sorted(type_changed),
        "new_optional": sorted(new_optional)[:_MAX_BASELINE_FIELDS],
    }


def has_drift(drift: dict[str, list[str]] | None) -> bool:
    return bool(drift and (drift["missing"] or drift["type_changed"]))


def secrets_match(supplied: str, source: ApiSourceRecord) -> bool:
    return constant_time_equals(supplied, source.secret)


_ = (ClipFetchError, ClipForbidden)  # SSRF error family shared with clips
