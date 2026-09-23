"""来源级显示覆盖（F11 暂时隐藏 / F13 阅读起点）——SQL 唯一入口。

Lumi 自有状态：只影响「全部」时间线的显示过滤，不触碰 FreshRSS 的
抓取、订阅关系、已读/收藏（与禁用订阅、标记已读明确分开）。
时间一律 canonical UTC「Z」串；NULL = 该维度未启用。

字段更新用 sentinel 语义：``_UNSET`` = 不修改，``None`` = 清空该维度，
字符串 = 设置（归一化为 UTC Z）。
"""

from datetime import datetime
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


# F001：per-source 新鲜度预警阈值（小时）。NULL = 未启用。
STALE_ALERT_HOURS_MIN = 1
STALE_ALERT_HOURS_MAX = 24 * 365


def stale_alert_hours_valid(value: int) -> bool:
    """F001 阈值边界（整数小时；范围外的输入在路由层拒绝为 422）。"""
    return STALE_ALERT_HOURS_MIN <= value <= STALE_ALERT_HOURS_MAX


def _reader_style_from_row(row: Any) -> dict[str, Any] | None:
    import json as _json

    try:
        raw = row["reader_style_json"]
    except (IndexError, KeyError):
        raw = None
    if not raw:
        return None
    try:
        style = _json.loads(raw)
    except _json.JSONDecodeError:
        return None
    return style if isinstance(style, dict) and style else None


EXTRACT_POLICIES = ("rss", "web")

# F055：阅读样式覆盖允许的键与边界（超集拒绝、越界钳制）。
READER_STYLE_KEYS = {
    "fontSize": (12, 28),
    "lineHeight": (1.4, 2.6),
    "width": (480, 1600),
}


def extract_policy_valid(value: Any) -> bool:
    return value in EXTRACT_POLICIES


def validate_reader_style(raw: Any) -> dict[str, Any] | None:
    """F055：键值子集校验；未知键拒绝（ValueError），数值越界钳制。"""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("readerStyle 必须是对象。")
    unknown = set(raw) - set(READER_STYLE_KEYS)
    if unknown:
        raise ValueError(f"readerStyle 含未知键：{sorted(unknown)}")
    clean: dict[str, Any] = {}
    for key, (low, high) in READER_STYLE_KEYS.items():
        value = raw.get(key)
        if value is None:
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"readerStyle.{key} 必须是数字。")
        clean[key] = round(min(high, max(low, float(value))), 2)
    return clean or None


def _ai_disabled_from_row(row: Any) -> bool:
    try:
        value = row["ai_disabled"]
    except (IndexError, KeyError):
        return False
    return bool(value)


def _mute_windows_from_row(row: Any) -> list[dict[str, Any]] | None:
    """N015：mute_windows_json → 已验证窗口列表（损坏 JSON 诚实降级 None）。"""
    from lumirss.mute_windows import load_windows

    try:
        raw = row["mute_windows_json"]
    except (IndexError, KeyError):
        return None
    if not raw:
        return None
    try:
        return load_windows(raw)
    except ValueError:
        return None


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "feedUrl": str(row["feed_url"]),
        "hiddenUntil": row["hidden_until"],
        "showFrom": row["show_from"],
        "staleAlertHours": row["stale_alert_hours"],
        "extractPolicy": row["extract_policy"] or "rss",
        "readerStyle": _reader_style_from_row(row),
        "aiDisabled": _ai_disabled_from_row(row),
        "muteWindows": _mute_windows_from_row(row),
        "updatedAt": str(row["updated_at"] or ""),
    }


_STALE_DIMENSION_EMPTY = (
    "hidden_until IS NULL AND show_from IS NULL AND stale_alert_hours IS NULL"
)


class SourceOverrideStore:
    """CRUD over source_overrides (bounded table: one row per feed)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_overrides(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT feed_url, hidden_until, show_from, stale_alert_hours, extract_policy, reader_style_json, ai_disabled, mute_windows_json, updated_at FROM source_overrides WHERE hidden_until IS NOT NULL OR show_from IS NOT NULL OR stale_alert_hours IS NOT NULL OR mute_windows_json IS NOT NULL ORDER BY updated_at DESC"
        )
        return [_row_to_dict(row) for row in rows]

    async def get_override(self, feed_url: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT feed_url, hidden_until, show_from, stale_alert_hours, extract_policy, reader_style_json, ai_disabled, mute_windows_json, updated_at FROM source_overrides WHERE feed_url = ?",
            (feed_url,),
        )
        if row is None:
            return None
        result = _row_to_dict(row)
        # F048/F055：提取策略（≠rss）与阅读样式覆盖也算有效覆盖，
        # 否则仅设置策略的来源会被当成「无覆盖」丢弃。
        if (
            result["hiddenUntil"] is None
            and result["showFrom"] is None
            and result["staleAlertHours"] is None
            and result["extractPolicy"] == "rss"
            and result["readerStyle"] is None
            and not result["aiDisabled"]
            and result["muteWindows"] is None
        ):
            return None
        return result

    async def set_fields(
        self,
        feed_url: str,
        *,
        hidden_until: Any = _UNSET,
        show_from: Any = _UNSET,
        stale_alert_hours: Any = _UNSET,
    ) -> dict[str, Any]:
        """更新单个 feed 的覆盖维度（sentinel 语义见模块 docstring）。"""
        await self._db.migrate()
        current = await self._db.fetch_one(
            "SELECT hidden_until, show_from, stale_alert_hours, extract_policy FROM source_overrides WHERE feed_url = ?",
            (feed_url,),
        )

        def _resolve(value: Any, current_value: Any) -> str | None:
            if value is _UNSET:
                return current_value
            if value is None:
                return None
            return canonical_utc(str(value))

        def _resolve_int(value: Any, current_value: Any) -> int | None:
            if value is _UNSET:
                return current_value
            if value is None:
                return None
            return int(value)

        hidden_value = _resolve(hidden_until, current["hidden_until"] if current else None)
        show_value = _resolve(show_from, current["show_from"] if current else None)
        stale_value = _resolve_int(
            stale_alert_hours, current["stale_alert_hours"] if current else None
        )
        policy_value = (
            current["extract_policy"] if current is not None else "rss"
        )
        await self._db.execute(
            "INSERT INTO source_overrides (feed_url, hidden_until, show_from, stale_alert_hours, extract_policy, updated_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(feed_url) DO UPDATE SET hidden_until = excluded.hidden_until, show_from = excluded.show_from, stale_alert_hours = excluded.stale_alert_hours, extract_policy = excluded.extract_policy, updated_at = excluded.updated_at",
            (feed_url, hidden_value, show_value, stale_value, policy_value or "rss", utc_now()),
        )
        if hidden_value is None and show_value is None and stale_value is None:
            # 所有时间维度都空 → 清理行，保持表紧凑（F066：ai_disabled/
            # extract_policy/reader_style/mute_windows 等其它维度仍有时保留）。
            row = await self._db.fetch_one(
                "SELECT ai_disabled, extract_policy, reader_style_json, mute_windows_json FROM source_overrides WHERE feed_url = ?",
                (feed_url,),
            )
            keep = (
                row is not None
                and (
                    bool(row["ai_disabled"])
                    or (row["extract_policy"] or "rss") != "rss"
                    or bool(row["reader_style_json"])
                    or bool(row["mute_windows_json"])
                )
            )
            if not keep:
                await self._db.execute(
                    "DELETE FROM source_overrides WHERE feed_url = ?",
                    (feed_url,),
                )
        result = await self.get_override(feed_url)
        if result is not None:
            return result
        return {
            "feedUrl": feed_url,
            "hiddenUntil": None,
            "showFrom": None,
            "staleAlertHours": None,
            "updatedAt": utc_now(),
        }

    async def set_extract_policy(self, feed_url: str, policy: str) -> None:
        """F048：设置 per-source 正文提取策略（'rss' | 'web'）。"""
        if not extract_policy_valid(policy):
            raise ValueError("extract policy must be 'rss' or 'web'.")
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT extract_policy FROM source_overrides WHERE feed_url = ?",
            (feed_url,),
        )
        current = row["extract_policy"] if row is not None else "rss"
        if row is None:
            await self._db.execute(
                "INSERT INTO source_overrides (feed_url, hidden_until, show_from, stale_alert_hours, extract_policy, updated_at) VALUES (?, NULL, NULL, NULL, ?, ?)",
                (feed_url, policy, utc_now()),
            )
        elif current != policy:
            await self._db.execute(
                "UPDATE source_overrides SET extract_policy = ?, updated_at = ? WHERE feed_url = ?",
                (policy, utc_now(), feed_url),
            )

    async def get_extract_policy(self, feed_url: str) -> str:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT extract_policy FROM source_overrides WHERE feed_url = ?",
            (feed_url,),
        )
        return (row["extract_policy"] if row is not None and row["extract_policy"] else "rss")

    async def set_reader_style(self, feed_url: str, style: dict[str, Any] | None) -> None:
        """F055：per-source 阅读样式覆盖（fontSize/lineHeight/width 子集）。

        存 JSON 文本；None = 恢复跟随全局（清空键）。列复用
        reader_style_json（见迁移 0048）。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT extract_policy FROM source_overrides WHERE feed_url = ?",
            (feed_url,),
        )
        import json as _json

        if style is None or not style:
            if row is None:
                return
            await self._db.execute(
                "UPDATE source_overrides SET reader_style_json = NULL, updated_at = ? WHERE feed_url = ?",
                (utc_now(), feed_url),
            )
            return
        payload = _json.dumps(style, ensure_ascii=False, separators=(",", ":"))
        if row is None:
            await self._db.execute(
                "INSERT INTO source_overrides (feed_url, hidden_until, show_from, stale_alert_hours, extract_policy, reader_style_json, updated_at) VALUES (?, NULL, NULL, NULL, 'rss', ?, ?)",
                (feed_url, payload, utc_now()),
            )
        else:
            await self._db.execute(
                "UPDATE source_overrides SET reader_style_json = ?, updated_at = ? WHERE feed_url = ?",
                (payload, utc_now(), feed_url),
            )

    async def get_reader_style(self, feed_url: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT reader_style_json FROM source_overrides WHERE feed_url = ?",
            (feed_url,),
        )
        if row is None or not row["reader_style_json"]:
            return None
        import json as _json

        try:
            style = _json.loads(row["reader_style_json"])
        except _json.JSONDecodeError:
            return None
        return style if isinstance(style, dict) and style else None

    async def stale_alert_configs(self) -> dict[str, int]:
        """F001：已启用新鲜度预警的 feed_url → 阈值小时数。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT feed_url, stale_alert_hours FROM source_overrides WHERE stale_alert_hours IS NOT NULL"
        )
        return {str(row["feed_url"]): int(row["stale_alert_hours"]) for row in rows}

    async def active_hidden_feed_urls(self, now_iso: str | None = None) -> list[str]:
        """当前处于隐藏期的 feed_url 列表（hidden_until > now）。"""
        await self._db.migrate()
        moment = now_iso or utc_now()
        rows = await self._db.fetch_all(
            "SELECT feed_url FROM source_overrides WHERE hidden_until IS NOT NULL AND hidden_until > ?",
            (moment,),
        )
        return [str(row["feed_url"]) for row in rows]


async def filter_timeline_items(
    db: Database, items: list[Any], *, now_local: datetime | None = None
) -> list[Any]:
    """F11/F13/N015：对「全部/未读」通用时间线应用来源覆盖过滤。

    - F11：hidden_until 未到期的来源条目被过滤（到期自动恢复）；
    - F13：show_from 之后发布才显示（更早历史在全部时间线隐藏，
      来源自身视图不受影响——显式选择该来源 = 用户明确要看）；
    - N015：mute_windows 命中当前本地墙钟时该来源条目被过滤（周期
      性，无到期概念；窗口未命中自动恢复）。
    feed 归属经派生投影（search_entries）解析；投影未覆盖的条目按
    「未知 ≠ 隐藏」保留（投影落后是暂态，不造成静默丢失）。页面小、
    IN 查询有界；无任何覆盖行时零额外查询直接返回。

    N015 时区口径：服务器本地墙钟（与 mail_digest 回退语义一致）；
    ``now_local`` 可注入（测试用），缺省取真实当前时间。"""
    from lumirss.mute_windows import any_window_hit, load_windows

    await db.migrate()
    rows = await db.fetch_all(
        "SELECT feed_url, hidden_until, show_from, mute_windows_json FROM source_overrides WHERE hidden_until IS NOT NULL OR show_from IS NOT NULL OR mute_windows_json IS NOT NULL"
    )
    if not rows:
        return items
    now_iso = utc_now()
    local_now = now_local or datetime.now().astimezone()
    hidden = {
        str(row["feed_url"])
        for row in rows
        if row["hidden_until"] and row["hidden_until"] > now_iso
    }
    show_from_map = {
        str(row["feed_url"]): str(row["show_from"]) for row in rows if row["show_from"]
    }
    muted_windows: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        raw = row["mute_windows_json"]
        if not raw:
            continue
        try:
            windows = load_windows(raw)
        except ValueError:
            continue  # 损坏窗口定义诚实降级为「不静音」
        muted_windows[str(row["feed_url"])] = windows
    if not hidden and not show_from_map and not muted_windows:
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
            if any_window_hit(muted_windows.get(feed_url), local_now):
                continue  # N015：分时静音窗口命中，不在通用时间线出现
            show_from = show_from_map.get(feed_url)
            published = ref_published.get(item.entryRef)
            if show_from and published and published < show_from:
                continue  # F13：早于阅读起点的历史在通用时间线隐藏
        kept.append(item)
    return kept
