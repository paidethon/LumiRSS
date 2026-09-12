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
import hmac
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
from lumirss.util import utc_now

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


class ApiSourceExpressionError(Exception):
    """JMESPath expression failed to compile or evaluate."""


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
    if parts.scheme != "https" or not parts.netloc:
        raise ApiSourceInvalid("API endpoint must be an absolute https URL.")
    if len(url) > 2048:
        raise ApiSourceInvalid("API endpoint is too long.")
    return url.strip()


def parse_field_map(raw: str) -> dict[str, str]:
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


async def fetch_json(http_client: httpx.AsyncClient, endpoint: str) -> Any:
    """SSRF-checked, size-capped (streamed), JSON-only fetch of the endpoint.

    The response body is streamed with a hard cap instead of being read
    whole first (P0-05f): buffering the full body before the size check
    let an oversized endpoint OOM the BFF. The dial goes through the
    pinned-IP transport (P0-03/P0-05): validate_hop's getaddrinfo check
    alone is TOCTOU-racy — DNS may re-resolve between check and connect;
    the transport re-validates and dials the verified address."""
    await validate_hop(endpoint)
    pinned_client = _pinned_client()
    try:
        request = pinned_client.build_request(
            "GET",
            endpoint,
            headers={"accept": "application/json"},
            timeout=_FETCH_TIMEOUT_SECONDS,
        )
        try:
            response = await pinned_client.send(request, stream=True, follow_redirects=False)
        except httpx.HTTPError as exc:
            raise ApiSourceFetchFailed("API 端点连接失败。") from exc
        try:
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
        for item in items[:_MAX_ITEMS]
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


def secrets_match(supplied: str, source: ApiSourceRecord) -> bool:
    return hmac.compare_digest(supplied, source.secret)


_ = (ClipFetchError, ClipForbidden)  # SSRF error family shared with clips
