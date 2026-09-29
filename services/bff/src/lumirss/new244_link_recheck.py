"""NEW-244 链接存活复核 —— 批量有界检查 + 四档诚实结果台账。

语义边界（模块存在的理由）：

- 用户选一批资料（refs），每个 ref 解析成一个待检 URL：
  * ``library:<uuid>`` → url 型书签的 url 列；
  * ``rss:<entryRef>`` → search_entries.url（投影未命中 → unknown，
    detail=projection_missing；资料没有 URL → unknown，detail=no_url）；
- 检查复用 F087 LinkCheckService：并发 ≤4、HEAD→有界 GET、8s 超时、
  SSRF 校验（私网/回环直接 blocked→unknown）、重定向 ≤5 跳——这是
  「有界检查」的既有实现，本模块不重写传输层；
- 四档结果只忠实转述探测事实：
  * ok → 2xx；redirect → 重定向后 2xx（报 finalUrl）；
    dead → 404/410；unknown → 其余一切（超时/网络错误/需登录/限流/
    SSRF 拦截/无法解析）。无法判断绝不冒充失效；
- 结果逐条落 link_recheck_results 台账（追加，不改写书签 URL）；
  同批复核有界（refs ≤ 50）。

per-user 库：结果天然按账户隔离。
"""

import uuid as _uuid
from typing import Any

from lumirss.bookmarks_check import LinkCheckService
from lumirss.db_tx import transaction
from lumirss.entryref import InvalidEntryReference, decode_entry_ref
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_REFS = 50
_HISTORY_LIMIT = 100

# LinkCheckService raw status → 四档诚实分类
_STATUS_MAP: dict[str, str] = {
    "ok": "ok",
    "redirect": "redirect",
    "not_found": "dead",
    "auth_required": "unknown",
    "rate_limited": "unknown",
    "timeout": "unknown",
    "network_error": "unknown",
    "blocked_ssrf": "unknown",
    "invalid_url": "unknown",
}


class LinkRecheckInvalid(ValueError):
    """复核请求非法（映射 422）。"""


def _classify(raw: dict[str, Any]) -> str:
    return _STATUS_MAP.get(str(raw.get("status")), "unknown")


class LinkRecheckService:
    def __init__(self, db: Database, checker: LinkCheckService | None = None) -> None:
        self._db = db
        self._checker = checker or LinkCheckService()

    # -- ref → url 解析 ----------------------------------------------------

    async def _resolve_url(self, ref: str) -> tuple[str | None, str]:
        """(url, detail)；url=None 时 detail 说明为什么检不了。"""
        if ref.startswith("library:"):
            row = await self._db.fetch_one(
                "SELECT b.url FROM library_bookmarks b JOIN library_items i ON i.uuid = b.item_uuid "
                "WHERE b.item_uuid = ? AND i.deleted_at IS NULL",
                (ref.removeprefix("library:"),),
            )
            if row is None:
                return None, "bookmark_missing"
            url = str(row["url"]) if row["url"] else ""
            return (url or None), ("" if url else "no_url")
        if ref.startswith("rss:"):
            raw_ref = ref.removeprefix("rss:")
            try:
                decode_entry_ref(raw_ref)  # 合法性校验（entryRef 可解码才受理）
            except InvalidEntryReference:
                return None, "bad_ref"
            row = await self._db.fetch_one(
                "SELECT url FROM search_entries WHERE entry_ref = ?",
                (raw_ref,),
            )
            if row is None:
                return None, "projection_missing"
            url = str(row["url"]) if row["url"] else ""
            return (url or None), ("" if url else "no_url")
        return None, "bad_ref"

    # -- 批量复核 ------------------------------------------------------------

    async def recheck(self, refs: list[str]) -> dict[str, Any]:
        """一批 ref → 逐条探测 → 四档结果落台账。"""
        if not isinstance(refs, list) or not refs:
            raise LinkRecheckInvalid("refs 不能为空。")
        if len(refs) > _MAX_REFS:
            raise LinkRecheckInvalid(f"单批复核最多 {_MAX_REFS} 条。")
        clean_refs: list[str] = []
        for ref in refs:
            if not isinstance(ref, str) or not 1 <= len(ref) <= 500:
                raise LinkRecheckInvalid("ref 格式非法。")
            clean_refs.append(ref)

        # 先解析（顺序去重；解析失败/缺 URL 的直接 unknown，不发起请求）
        resolved: dict[str, tuple[str | None, str]] = {}
        for ref in dict.fromkeys(clean_refs):
            resolved[ref] = await self._resolve_url(ref)

        checkable = {
            ref: url
            for ref, (url, _detail) in resolved.items()
            if url is not None
        }
        raw_results: dict[str, dict[str, Any]] = {}
        if checkable:
            probes = await self._checker.check_many(list(checkable.values()))
            by_url = {item["ref"]: item for item in probes}
            for ref, url in checkable.items():
                raw_results[ref] = by_url.get(url, {"status": "network_error"})

        now = utc_now()
        items: list[dict[str, Any]] = []
        for ref in dict.fromkeys(clean_refs):
            url, detail = resolved[ref]
            if url is None:
                status = "unknown"
            else:
                raw = raw_results[ref]
                status = _classify(raw)
                detail = str(raw.get("status"))
            row_id = str(_uuid.uuid4())
            http_status: int | None = None
            final_url: str | None = None
            if url is not None:
                raw = raw_results[ref]
                http_status = raw.get("http_status")
                final_url = raw.get("final_url")
            await self._persist(row_id, ref, url, status, http_status, final_url, detail, now)
            items.append(
                {
                    "id": row_id,
                    "ref": ref,
                    "url": url,
                    "status": status,
                    "httpStatus": http_status,
                    "finalUrl": final_url,
                    "detail": detail,
                    "checkedAt": now,
                }
            )
        return {"items": items, "checkedAt": now, "count": len(items)}

    async def _persist(
        self,
        row_id: str,
        ref: str,
        url: str | None,
        status: str,
        http_status: int | None,
        final_url: str | None,
        detail: str,
        now: str,
    ) -> None:
        def _tx(conn: Any) -> None:
            conn.execute(
                "INSERT INTO link_recheck_results (id, target_ref, url, status, http_status, final_url, detail, checked_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (row_id, ref, url, status, http_status, final_url, detail, now),
            )

        await transaction(self._db, _tx)

    # -- 台账 ----------------------------------------------------------------

    async def recent_results(self, *, limit: int = 50) -> dict[str, Any]:
        """最近台账（新→旧；有界）。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, target_ref, url, status, http_status, final_url, detail, checked_at "
            "FROM link_recheck_results ORDER BY checked_at DESC, rowid DESC LIMIT ?",
            (max(1, min(limit, _HISTORY_LIMIT)),),
        )
        return {
            "items": [
                {
                    "id": str(row["id"]),
                    "ref": str(row["target_ref"]),
                    "url": str(row["url"]) if row["url"] else None,
                    "status": str(row["status"]),
                    "httpStatus": row["http_status"],
                    "finalUrl": str(row["final_url"]) if row["final_url"] else None,
                    "detail": str(row["detail"]),
                    "checkedAt": str(row["checked_at"]),
                }
                for row in rows
            ]
        }
