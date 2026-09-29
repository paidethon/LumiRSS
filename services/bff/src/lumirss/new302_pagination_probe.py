"""NEW-302 API 分页试抓台 —— 用受限次数验证已配置接口的分页契约。

- 试抓走与生产相同的 SSRF 校验与 JSON 解析（复用 api_sources 的
  fetch_json），但**独立于生产发布路径**：单页失败不中断整个试抓
  （生产是原子中止），而是把该页记为缺失（gap）继续 —— 试抓台的
  使命是诊断契约，不是发布；
- 硬上限：试抓最多 5 页（无论来源配置多大 max_pages）、每页条数按
  生产 items 表达式统计 —— 永不自动无限抓取；
- 摘要脱敏：页 URL 只显示 形状（scheme/host/path + 查询参数名），
  不显示参数值 —— query 里可能带令牌/游标；
- duplicate = 载荷摘要与更早某页完全相同的页（重复页契约警告）；
  gap = 拉取失败（缺页）；
- 每来源只保留最近一次试抓结果（诊断快照，表有界）；
- per-user：来源与试抓结果都在 per-user 库，B 访问 A 的来源 404。
"""

import hashlib
import json
import urllib.parse
from typing import Any

from lumirss.api_sources import (
    ApiSourceFetchFailed,
    fetch_json,
    parse_pagination,
)
from lumirss.storage import Database
from lumirss.util import utc_now

PROBE_MAX_PAGES = 5
_PAGE_QUERY_WINDOW = 100


class ProbeTargetNotFound(Exception):
    """来源不存在（对当前用户而言）。"""


class PaginationProbeInvalid(ValueError):
    """试抓参数非法（映射 422）。"""


def clean_probe_max_pages(raw: Any) -> int:
    if raw is None:
        return PROBE_MAX_PAGES
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise PaginationProbeInvalid("maxPages 必须是整数。")
    if not 1 <= raw <= PROBE_MAX_PAGES:
        raise PaginationProbeInvalid(f"maxPages 必须在 1..{PROBE_MAX_PAGES} 之间。")
    return raw


def url_shape(url: str) -> str:
    """脱敏 URL 形状：scheme://host/path + 「?参数名&参数名」。

    查询参数值可能内嵌令牌/游标 —— 一律不显示。"""
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    names = [name for name, _value in query]
    shape = f"{parts.scheme}://{parts.netloc}{parts.path}"
    if names:
        shape += "?" + "&".join(names)
    return shape


def _url_with_param(endpoint: str, key: str, value: str) -> str:
    parts = urllib.parse.urlsplit(endpoint)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query = [(k, v) for k, v in query if k != key]
    query.append((key, value))
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), parts.fragment)
    )


def _page_item_count(payload: Any, items_expr: str) -> int:
    import jmespath

    try:
        result = jmespath.search(items_expr, payload)
    except Exception:
        return 1
    return len(result) if isinstance(result, list) else 1


async def run_probe(
    http_client: Any,
    endpoint: str,
    pagination_raw: str | None,
    items_expr: str,
    *,
    max_pages: int = PROBE_MAX_PAGES,
    fetch=None,
) -> dict[str, Any]:
    """有界试抓：逐页记录摘要，单页失败记 gap 继续，永不无限。

    ``fetch`` 可注入（测试用假传输；生产默认 = api_sources.fetch_json，
    含完整 SSRF 校验与 2MB/JSON 限制）。"""
    walk = fetch or fetch_json
    config = parse_pagination(pagination_raw)
    mode = config.get("mode", "none")
    pages: list[dict[str, Any]] = []
    digests: set[str] = set()
    duplicates = 0
    gaps = 0
    total_items = 0
    stop_reason = "max_pages"

    async def probe_page(url: str, page_label: int | str) -> tuple[dict[str, Any], Any]:
        entry: dict[str, Any] = {"page": page_label, "url": url_shape(url)}
        try:
            payload = await walk(http_client, url)
        except ApiSourceFetchFailed as exc:
            entry["error"] = str(exc)[:200]
            entry["itemCount"] = 0
            return entry, None
        entry["itemCount"] = _page_item_count(payload, items_expr)
        entry["digest"] = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:16]
        return entry, payload

    if mode == "none":
        entry, _payload = await probe_page(endpoint, 1)
        pages.append(entry)
        stop_reason = "single"
    elif mode == "page":
        page_param = str(config.get("page_param", "page"))
        first_page = int(config.get("first_page", 1))
        for offset in range(max_pages):
            page_number = first_page + offset
            target = _url_with_param(endpoint, page_param, str(page_number))
            if len(target) > 2048 + _PAGE_QUERY_WINDOW:
                stop_reason = "url_overflow"
                break
            entry, _payload = await probe_page(target, page_number)
            if "error" in entry:
                gaps += 1
            else:
                if entry["digest"] in digests:
                    entry["duplicate"] = True
                    duplicates += 1
                digests.add(entry["digest"])
                total_items += int(entry["itemCount"])
                if int(entry["itemCount"]) == 0:
                    pages.append(entry)
                    stop_reason = "empty_page"
                    break
            pages.append(entry)
    else:  # cursor
        cursor_path = str(config.get("cursor_path", ""))
        seen: list[str] = []
        target = endpoint
        for index in range(max_pages):
            entry, payload_now = await probe_page(target, index + 1)
            if "error" in entry:
                gaps += 1
                pages.append(entry)
                stop_reason = "page_error"
                break
            if entry["digest"] in digests:
                entry["duplicate"] = True
                duplicates += 1
            digests.add(entry["digest"])
            total_items += int(entry["itemCount"])
            pages.append(entry)
            import jmespath

            try:
                cursor = jmespath.search(cursor_path, payload_now)
            except Exception:
                cursor = None
            if cursor is None or (isinstance(cursor, str) and not cursor.strip()):
                stop_reason = "cursor_missing"
                break
            cursor_text = str(cursor)
            if cursor_text in seen:
                stop_reason = "cursor_repeat"
                break
            seen.append(cursor_text)
            target = _url_with_param(endpoint, "cursor", cursor_text)
            if len(target) > 2048 + _PAGE_QUERY_WINDOW:
                stop_reason = "url_overflow"
                break
    return {
        "probedAt": utc_now(),
        "mode": mode,
        "stopReason": stop_reason,
        "pageCount": len(pages),
        "itemCount": total_items,
        "duplicatePages": duplicates,
        "gapPages": gaps,
        "pages": pages,
    }


class PaginationProbeStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def save_result(self, source_uuid: str, result: dict[str, Any]) -> dict[str, Any]:
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO api_pagination_probes (source_uuid, probed_at, stop_reason, page_count, "
            "item_count, duplicate_pages, gap_pages, pages) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(source_uuid) DO UPDATE SET probed_at = excluded.probed_at, "
            "stop_reason = excluded.stop_reason, page_count = excluded.page_count, "
            "item_count = excluded.item_count, duplicate_pages = excluded.duplicate_pages, "
            "gap_pages = excluded.gap_pages, pages = excluded.pages",
            (
                source_uuid,
                result["probedAt"],
                result["stopReason"],
                result["pageCount"],
                result["itemCount"],
                result["duplicatePages"],
                result["gapPages"],
                json.dumps(result["pages"], ensure_ascii=False, separators=(",", ":")),
            ),
        )
        return result

    async def last_result(self, source_uuid: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT source_uuid, probed_at, stop_reason, page_count, item_count, "
            "duplicate_pages, gap_pages, pages FROM api_pagination_probes WHERE source_uuid = ?",
            (source_uuid,),
        )
        if row is None:
            return None
        try:
            pages = json.loads(str(row["pages"]))
        except json.JSONDecodeError:
            pages = []
        return {
            "sourceUuid": str(row["source_uuid"]),
            "probedAt": str(row["probed_at"]),
            "stopReason": str(row["stop_reason"]),
            "pageCount": int(row["page_count"]),
            "itemCount": int(row["item_count"]),
            "duplicatePages": int(row["duplicate_pages"]),
            "gapPages": int(row["gap_pages"]),
            "pages": pages,
        }
