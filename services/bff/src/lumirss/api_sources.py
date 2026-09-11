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
- Atom: generated with stdlib escaping; entry IDs are stable
  (deterministic from the mapped id field + source uuid); ETag/304.
- Feed URL carries a per-source high-entropy secret compared in constant
  time (it is the credential — the endpoint lives OUTSIDE /api/* so the
  browser middlewares don't apply, FreshRSS dials it directly).
"""

import hashlib
import hmac
import json
import secrets as _secrets
import urllib.parse
import xml.sax.saxutils as _xml
from dataclasses import dataclass
from typing import Any

import httpx
import jmespath

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


async def fetch_json(http_client: httpx.AsyncClient, endpoint: str) -> Any:
    """SSRF-checked, size-capped, JSON-only fetch of the endpoint."""
    await validate_hop(endpoint)
    try:
        response = await http_client.get(
            endpoint,
            follow_redirects=False,
            headers={"accept": "application/json"},
            timeout=_FETCH_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise ApiSourceFetchFailed("API 端点连接失败。") from exc
    try:
        if response.status_code != 200:
            raise ApiSourceFetchFailed(f"API 端点返回 HTTP {response.status_code}。")
        content_type = response.headers.get("content-type", "").lower()
        body = await response.aread()
    finally:
        await response.aclose()
    if "json" not in content_type:
        raise ApiSourceFetchFailed("API 端点未返回 JSON。")
    if len(body) > _MAX_JSON_BYTES:
        raise ApiSourceFetchFailed("API 响应超过 2MB 上限。")
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApiSourceFetchFailed("API 响应不是有效 JSON。") from exc


# -- Atom generation --------------------------------------------------------


def _entry_id(source_uuid: str, item: dict[str, Any]) -> str:
    raw = str(item.get("id"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"urn:lumirss:apisource:{source_uuid}:{digest}"


def _atom_escape(text: str) -> str:
    return _xml.escape(text)


def generate_atom(
    source: ApiSourceRecord, items: list[dict[str, Any]], self_base: str
) -> str:
    """Deterministic Atom 2.0 feed with stable entry ids and stdlib escaping."""
    feed_self = f"{self_base}{atom_path(source.uuid, source.secret)}"
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        f"  <title>{_atom_escape(source.name)}</title>",
        f"  <id>urn:lumirss:apisource:{source.uuid}</id>",
        f'  <updated>{_atom_escape(utc_now())}</updated>',
        f'  <link rel="self" href="{_atom_escape(feed_self)}"/>',
    ]
    for item in items[:_MAX_ITEMS]:
        entry_id = _entry_id(source.uuid, item)
        title = str(item.get("title") or "(无标题)")
        url = item.get("url")
        published = item.get("published")
        body = item.get("body") or ""
        lines.append("  <entry>")
        lines.append(f"    <id>{_atom_escape(entry_id)}</id>")
        lines.append(f"    <title>{_atom_escape(title)}</title>")
        if url:
            lines.append(f'    <link href="{_atom_escape(str(url))}"/>')
        if published:
            lines.append(
                f'    <published>{_atom_escape(str(published))}</published>'
            )
        lines.append(
            f'    <content type="html">{_atom_escape(str(body))}</content>'
        )
        lines.append("  </entry>")
    lines.append("</feed>")
    return "\n".join(lines) + "\n"


def feed_etag(atom_xml: str) -> str:
    return '"' + hashlib.sha256(atom_xml.encode("utf-8")).hexdigest()[:32] + '"'


def secrets_match(supplied: str, source: ApiSourceRecord) -> bool:
    return hmac.compare_digest(supplied, source.secret)


_ = (ClipFetchError, ClipForbidden)  # SSRF error family shared with clips
