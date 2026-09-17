"""来源级显示覆盖（F11 暂时隐藏 / F13 阅读起点）——SQL 唯一入口。

Lumi 自有状态：只影响「全部」时间线的显示过滤，不触碰 FreshRSS 的
抓取、订阅关系、已读/收藏（与禁用订阅、标记已读明确分开）。
时间一律 canonical UTC「Z」串；NULL = 该维度未启用。

字段更新用 sentinel 语义：``_UNSET`` = 不修改，``None`` = 清空该维度，
字符串 = 设置（归一化为 UTC Z）。
"""

from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

_UNSET = object()


def canonical_utc(value: str) -> str | None:
    """任意 RFC3339 形态 → 统一 UTC「Z」串；解析失败 → None。"""
    if not isinstance(value, str) or not value.strip():
        return None
    from datetime import UTC, datetime

    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "feedUrl": str(row["feed_url"]),
        "hiddenUntil": row["hidden_until"],
        "showFrom": row["show_from"],
        "updatedAt": str(row["updated_at"] or ""),
    }


class SourceOverrideStore:
    """CRUD over source_overrides (bounded table: one row per feed)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_overrides(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT feed_url, hidden_until, show_from, updated_at FROM source_overrides WHERE hidden_until IS NOT NULL OR show_from IS NOT NULL ORDER BY updated_at DESC"
        )
        return [_row_to_dict(row) for row in rows]

    async def get_override(self, feed_url: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT feed_url, hidden_until, show_from, updated_at FROM source_overrides WHERE feed_url = ?",
            (feed_url,),
        )
        if row is None:
            return None
        result = _row_to_dict(row)
        if result["hiddenUntil"] is None and result["showFrom"] is None:
            return None
        return result

    async def set_fields(
        self,
        feed_url: str,
        *,
        hidden_until: Any = _UNSET,
        show_from: Any = _UNSET,
    ) -> dict[str, Any]:
        """更新单个 feed 的覆盖维度（sentinel 语义见模块 docstring）。"""
        await self._db.migrate()
        current = await self._db.fetch_one(
            "SELECT hidden_until, show_from FROM source_overrides WHERE feed_url = ?",
            (feed_url,),
        )

        def _resolve(value: Any, current_value: Any) -> str | None:
            if value is _UNSET:
                return current_value
            if value is None:
                return None
            return canonical_utc(str(value))

        hidden_value = _resolve(hidden_until, current["hidden_until"] if current else None)
        show_value = _resolve(show_from, current["show_from"] if current else None)
        await self._db.execute(
            "INSERT INTO source_overrides (feed_url, hidden_until, show_from, updated_at) VALUES (?, ?, ?, ?) ON CONFLICT(feed_url) DO UPDATE SET hidden_until = excluded.hidden_until, show_from = excluded.show_from, updated_at = excluded.updated_at",
            (feed_url, hidden_value, show_value, utc_now()),
        )
        if hidden_value is None and show_value is None:
            # 两个字段都空 → 清理行，保持表紧凑
            await self._db.execute(
                "DELETE FROM source_overrides WHERE feed_url = ?",
                (feed_url,),
            )
        result = await self.get_override(feed_url)
        if result is not None:
            return result
        return {"feedUrl": feed_url, "hiddenUntil": None, "showFrom": None, "updatedAt": utc_now()}

    async def active_hidden_feed_urls(self, now_iso: str | None = None) -> list[str]:
        """当前处于隐藏期的 feed_url 列表（hidden_until > now）。"""
        await self._db.migrate()
        moment = now_iso or utc_now()
        rows = await self._db.fetch_all(
            "SELECT feed_url FROM source_overrides WHERE hidden_until IS NOT NULL AND hidden_until > ?",
            (moment,),
        )
        return [str(row["feed_url"]) for row in rows]


async def filter_timeline_items(db: Database, items: list[Any]) -> list[Any]:
    """F11/F13：对「全部/未读」通用时间线应用来源覆盖过滤。

    - F11：hidden_until 未到期的来源条目被过滤（到期自动恢复）；
    - F13：show_from 之后发布才显示（更早历史在全部时间线隐藏，
      来源自身视图不受影响——显式选择该来源 = 用户明确要看）。
    feed 归属经派生投影（search_entries）解析；投影未覆盖的条目按
    「未知 ≠ 隐藏」保留（投影落后是暂态，不造成静默丢失）。页面小、
    IN 查询有界；无任何覆盖行时零额外查询直接返回。"""
    await db.migrate()
    rows = await db.fetch_all(
        "SELECT feed_url, hidden_until, show_from FROM source_overrides WHERE hidden_until IS NOT NULL OR show_from IS NOT NULL"
    )
    if not rows:
        return items
    now_iso = utc_now()
    hidden = {
        str(row["feed_url"])
        for row in rows
        if row["hidden_until"] and row["hidden_until"] > now_iso
    }
    show_from_map = {
        str(row["feed_url"]): str(row["show_from"]) for row in rows if row["show_from"]
    }
    if not hidden and not show_from_map:
        return items
    refs = [item.entryRef for item in items]
    placeholders = ",".join("?" for _ in refs)
    ref_rows = await db.fetch_all(
        f"SELECT entry_ref, feed_url, published_at FROM search_entries WHERE entry_ref IN ({placeholders})",
        tuple(refs),
    )
    ref_feed = {str(r["entry_ref"]): str(r["feed_url"]) for r in ref_rows}
    ref_published = {str(r["entry_ref"]): str(r["published_at"]) for r in ref_rows}
    kept: list[Any] = []
    for item in items:
        feed_url = ref_feed.get(item.entryRef)
        if feed_url is not None:
            if feed_url in hidden:
                continue  # F11：隐藏期内不出现在通用时间线
            show_from = show_from_map.get(feed_url)
            published = ref_published.get(item.entryRef)
            if show_from and published and published < show_from:
                continue  # F13：早于阅读起点的历史在通用时间线隐藏
        kept.append(item)
    return kept
