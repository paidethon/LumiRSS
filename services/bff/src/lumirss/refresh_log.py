"""N036 刷新队列可视化 + N037 断更恢复补读 —— SQL 唯一入口。

Lumi 自有状态（每用户库，无 user_id 列），两类有界记录：

- ``source_refresh_log``：每来源最近 20 条检查记录。写入路径**恰好两条**
  （负向契约：本模块没有、也绝不添加任何调度器）：
  1. F050 手动健康探测（POST /api/v1/subscriptions/health-check）——
     用户点「立即检查」时逐源记录；探测不数条目，entry_count 恒 0；
  2. 投影增量同步（SearchIndexService.sync_incremental）——只对**确有
     新交付**的来源记 ok 行（entry_count = 该源本次交付条数）。同步是
     全量扫描、无法为「无变化」的来源诚实产出 per-feed 检查记录，
     故不为它们编造行（读取侧以「无记录」诚实呈现）。

- ``feed_recovery``（N037）：``error|stale → ok`` 跳变时记一行恢复窗口
  （window_start = 连续非 ok 序列起点，window_end = 恢复时刻，
  entry_refs ≤50 = 窗口内该来源的投影条目）；``consumed`` 一次性消费
  锚点——to-queue 后置 1，重复消费 409。

result 分类（probe 路径）：上游 F050 状态 → ok | stale | error 归并：
- ``ok``：可达且投影最新条目未超阈值（默认 7×24h，或 F001
  stale_alert_hours 覆盖）；
- ``stale``：可达但投影最新条目早于阈值（断更中）；
- ``error``：auth_error/not_found/rate_limited/timeout/bad_content/
  network_error 一律归并（呈现层不需要细分，日志保持三类）。
"""

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.util import utc_now

_KEEP_PER_FEED = 20
_RECOVERY_REFS_LIMIT = 50
_RECOVERY_LIST_LIMIT = 50
_RECENT_LIMIT = 5

# 断更阈值兜底（小时）：来源未设置 F001 stale_alert_hours 时的缺省。
_DEFAULT_STALE_HOURS = 24 * 7

RESULTS = ("ok", "stale", "error")


class RecoveryNotFound(Exception):
    """恢复窗口不存在（404 recovery_not_found）。"""


class RecoveryAlreadyConsumed(Exception):
    """恢复窗口已加入过补读队列（409 recovery_already_consumed）。"""


def _iso_to_epoch(value: str) -> int:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp())


def classify_probe_result(status: str) -> str:
    """F050 探测状态 → N036 三类归并（见模块 docstring）。"""
    if status == "ok":
        return "ok"
    if status in ("bad_content", "not_found", "auth_error", "rate_limited", "timeout", "network_error"):
        return "error"
    return "error"


class SourceRefreshLogStore:
    """Persistence for source_refresh_log / feed_recovery."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # -- writes ---------------------------------------------------------------

    async def record(
        self, feed_url: str, result: str, *, entry_count: int = 0, now: str | None = None
    ) -> dict[str, Any] | None:
        """记录一次检查；error/stale→ok 跳变时创建恢复窗口。

        返回新建的 recovery 视图（无跳变 → None）。任何投影查询失败都
        不阻断记录本身（恢复窗口的 refs 允许为空数组——窗口时间在，
        条目稍后仍可经队列手动加入）。
        """
        await self._db.migrate()
        if result not in RESULTS:
            raise ValueError("result must be ok|stale|error.")
        checked_at = now or utc_now()
        transition = await self._detect_transition(feed_url, result, checked_at)
        await self._db.execute(
            "INSERT INTO source_refresh_log (feed_url, checked_at, result, entry_count) VALUES (?, ?, ?, ?)",
            (feed_url, checked_at, result, int(entry_count)),
        )
        await self._prune_feed(feed_url)
        if transition is None:
            return None
        return await self._create_recovery(feed_url, transition, checked_at)

    async def _detect_transition(
        self, feed_url: str, result: str, checked_at: str
    ) -> str | None:
        """error/stale → ok 跳变检测：返回窗口起点（连续非 ok 序列的
        最早 checked_at）或 None。

        以插入序（id DESC）而非 checked_at 比较判定连续性——检查可能
        在同一秒内连续发生（秒级时间戳无法表达先后），id 序是唯一
        可靠的事实顺序。"""
        if result != "ok":
            return None
        rows = await self._db.fetch_all(
            "SELECT checked_at, result FROM source_refresh_log WHERE feed_url = ?"
            " ORDER BY id DESC LIMIT 50",
            (feed_url,),
        )
        if not rows or str(rows[0]["result"]) == "ok":
            return None  # 最新一条已是 ok：无活跃断更序列
        window_start = str(rows[0]["checked_at"])
        for row in rows:  # 从新到旧走到第一个 ok 为止
            if str(row["result"]) == "ok":
                break
            window_start = str(row["checked_at"])
        return window_start

    async def _prune_feed(self, feed_url: str) -> None:
        await self._db.execute(
            "DELETE FROM source_refresh_log WHERE feed_url = ? AND id NOT IN ("
            " SELECT id FROM source_refresh_log WHERE feed_url = ?"
            " ORDER BY checked_at DESC, id DESC LIMIT ?)",
            (feed_url, feed_url, _KEEP_PER_FEED),
        )

    async def _create_recovery(
        self, feed_url: str, window_start: str, window_end: str
    ) -> dict[str, Any]:
        refs = await self._window_refs(feed_url, window_start, window_end)
        recovery_id = f"rec-{uuid.uuid4().hex}"
        created_at = utc_now()
        await self._db.execute(
            "INSERT INTO feed_recovery (id, feed_url, window_start, window_end,"
            " entry_refs_json, consumed, created_at) VALUES (?, ?, ?, ?, ?, 0, ?)",
            (
                recovery_id,
                feed_url,
                window_start,
                window_end,
                json.dumps(refs, ensure_ascii=False, separators=(",", ":")),
                created_at,
            ),
        )
        return {
            "id": recovery_id,
            "feedUrl": feed_url,
            "windowStart": window_start,
            "windowEnd": window_end,
            "refCount": len(refs),
            "consumed": False,
            "createdAt": created_at,
        }

    async def _window_refs(
        self, feed_url: str, window_start: str, window_end: str
    ) -> list[str]:
        """窗口内该来源的投影条目（published_at 命中优先；不足 50 时用
        fetched_at（投影接收时刻，epoch）补齐——断更恢复的条目常见
        「恢复后才被同步投递」，其 published_at 是上游原始时间、可能早
        于 window_start，接收时刻才是窗口事实）。去重、≤50。"""
        await self._db.migrate()
        start_epoch = _iso_to_epoch(window_start)
        end_epoch = _iso_to_epoch(window_end)
        rows = await self._db.fetch_all(
            "SELECT entry_ref, published_at, fetched_at FROM search_entries"
            " WHERE feed_url = ? AND published_at >= ? AND published_at <= ?"
            " ORDER BY published_at DESC LIMIT ?",
            (feed_url, window_start, window_end, _RECOVERY_REFS_LIMIT),
        )
        refs = [str(row["entry_ref"]) for row in rows]
        if len(refs) < _RECOVERY_REFS_LIMIT:
            extra = await self._db.fetch_all(
                "SELECT entry_ref, published_at FROM search_entries"
                " WHERE feed_url = ? AND fetched_at >= ? AND fetched_at <= ?"
                " ORDER BY fetched_at DESC LIMIT ?",
                (feed_url, start_epoch, end_epoch, _RECOVERY_REFS_LIMIT * 2),
            )
            for row in extra:
                ref = str(row["entry_ref"])
                if ref not in refs:
                    refs.append(ref)
                if len(refs) >= _RECOVERY_REFS_LIMIT:
                    break
        return refs[:_RECOVERY_REFS_LIMIT]

    # -- reads ---------------------------------------------------------------

    async def status_snapshot(self, *, now: str | None = None) -> dict[str, Any]:
        """GET /sources/refresh-status 视图：每来源 lastChecked/lastResult/
        pending + 最近 5 条；pending = 最近一次检查非 ok，或存在未消费
        恢复窗口（补读待处理）。无任何记录的来源不出现在响应里
        （诚实于「从未检查过」——不编造 pending=false）。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT feed_url, checked_at, result, entry_count"
            " FROM source_refresh_log ORDER BY feed_url ASC, checked_at ASC, id ASC"
        )
        per_feed: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            per_feed.setdefault(str(row["feed_url"]), []).append(
                {
                    "checkedAt": str(row["checked_at"]),
                    "result": str(row["result"]),
                    "entryCount": int(row["entry_count"]),
                }
            )
        unconsumed = await self._db.fetch_all(
            "SELECT DISTINCT feed_url FROM feed_recovery WHERE consumed = 0"
        )
        recovering = {str(row["feed_url"]) for row in unconsumed}
        feeds: list[dict[str, Any]] = []
        for feed_url, entries in sorted(per_feed.items()):
            recent = entries[-_RECENT_LIMIT:]
            last = entries[-1]
            feeds.append(
                {
                    "feedUrl": feed_url,
                    "lastChecked": last["checkedAt"],
                    "lastResult": last["result"],
                    "pending": last["result"] != "ok" or feed_url in recovering,
                    "recoveryAvailable": feed_url in recovering,
                    "recent": recent,
                }
            )
        return {"feeds": feeds, "checkedAt": now or utc_now()}

    async def latest_result(self, feed_url: str) -> str | None:
        row = await self._db.fetch_one(
            "SELECT result FROM source_refresh_log WHERE feed_url = ?"
            " ORDER BY checked_at DESC, id DESC LIMIT 1",
            (feed_url,),
        )
        return str(row["result"]) if row is not None else None

    async def newest_published_at(self, feed_url: str) -> str | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT MAX(published_at) AS newest FROM search_entries WHERE feed_url = ?",
            (feed_url,),
        )
        if row is None or row["newest"] is None:
            return None
        return str(row["newest"])

    async def stale_threshold_hours(self, feed_url: str) -> int:
        """F001 stale_alert_hours 覆盖优先；未设置 → 默认 7×24h。"""
        row = await self._db.fetch_one(
            "SELECT stale_alert_hours FROM source_overrides WHERE feed_url = ?",
            (feed_url,),
        )
        if row is not None and row["stale_alert_hours"]:
            return int(row["stale_alert_hours"])
        return _DEFAULT_STALE_HOURS

    # -- N037 recoveries ------------------------------------------------------

    async def recoveries(self, *, include_consumed: bool = True) -> list[dict[str, Any]]:
        await self._db.migrate()
        where = "" if include_consumed else " WHERE consumed = 0"
        rows = await self._db.fetch_all(
            "SELECT id, feed_url, window_start, window_end, entry_refs_json,"
            " consumed, created_at FROM feed_recovery" + where +
            " ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (_RECOVERY_LIST_LIMIT,),
        )
        views: list[dict[str, Any]] = []
        for row in rows:
            refs = _parse_refs(row["entry_refs_json"])
            views.append(
                {
                    "id": str(row["id"]),
                    "feedUrl": str(row["feed_url"]),
                    "windowStart": str(row["window_start"]),
                    "windowEnd": str(row["window_end"]),
                    "refCount": len(refs),
                    "consumed": bool(row["consumed"]),
                    "createdAt": str(row["created_at"]),
                }
            )
        return views

    async def recovery_refs(self, recovery_id: str) -> list[str]:
        row = await self._get_row(recovery_id)
        return _parse_refs(row["entry_refs_json"])

    async def consume_recovery(self, recovery_id: str) -> list[str]:
        """一次性消费：置 consumed=1 并返回 refs。已消费 → 409 语义。"""

        def _tx(conn: sqlite3.Connection) -> list[str]:
            row = conn.execute(
                "SELECT entry_refs_json, consumed FROM feed_recovery WHERE id = ?",
                (recovery_id,),
            ).fetchone()
            if row is None:
                raise RecoveryNotFound(recovery_id)
            if int(row["consumed"]) == 1:
                raise RecoveryAlreadyConsumed(recovery_id)
            conn.execute(
                "UPDATE feed_recovery SET consumed = 1 WHERE id = ?", (recovery_id,)
            )
            return _parse_refs(row["entry_refs_json"])

        return await transaction(self._db, _tx)

    async def _get_row(self, recovery_id: str) -> Any:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, feed_url, window_start, window_end, entry_refs_json,"
            " consumed, created_at FROM feed_recovery WHERE id = ?",
            (recovery_id,),
        )
        if row is None:
            raise RecoveryNotFound(recovery_id)
        return row


def _parse_refs(raw: Any) -> list[str]:
    try:
        parsed = json.loads(str(raw or "[]"))
    except ValueError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(ref) for ref in parsed if isinstance(ref, str) and ref]


def stale_cutoff_iso(now: "str | datetime", hours: int) -> str:
    """阈值时点（UTC Z 串）——``newest_published_at`` 早于它 = stale。

    ``now`` 接受 ISO 串（utc_now() 形态）或 datetime。"""
    if isinstance(now, str):
        try:
            now = datetime.fromisoformat(now.replace("Z", "+00:00"))
        except ValueError:
            now = datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
