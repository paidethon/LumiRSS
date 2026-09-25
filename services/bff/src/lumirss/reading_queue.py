"""N041 今日必读队列 —— 服务端持久化的每用户每日阅读队列。

+ N042 队列分段（行级 segment 标签 + meta 段顺序，N101 group 模式的镜像）；
+ N043 队列冻结快照（payload 只带 ItemRef + 顺序元数据，不可变）。

安全与诚实边界：

- ``reading_queue`` 是 Lumi 自有状态（每用户库，无 user_id 列）；行只存
  统一 ItemRef，绝不复制内容（ADR 0004）。条目删除/退订后行仍存在，
  解析失败由读取侧诚实呈现占位（绝不复活）；
- 生成算法的诚实基础：候选按 **未读 + N020 关注级别（must_read 优先，
  normal 次之，low 垫后；未设置级别 = normal）+ 近期（published_at
  recency）** 挑选；``levels`` 参数非空时候选池限定到指定级别。
  预算上限用粗估读时
  ``minutes = max(1, ceil(len(content_text) / 400))``（服务端只有投影
  纯文本；400 字符/分钟是有意的粗常量，与 Web 侧 CJK 感知估算不同源，
  响应以 ``basis``/``notes`` 字段诚实标注）。若一个候选都装不下且确有
  未读，收进最近一篇（宁可超预算也不交空队列，诚实于「budget 是估算」）；
- 幂等（N041 CRITICAL）：当天队列一旦存在（含手动加入的行、done 行），
  再次 generate 原样返回现有队列（``generated=false``）——后台刷新绝不
  重排已确认的队列；``force=1`` 才重建：清掉 pending/removed 行后重新
  装填，done 行与其完成状态原样保留（完成按条目身份记账，绝不因重建
  复活或丢失）；被手动移除的条目绝不因重新生成而复活；
- done/removed 是 set 语义；「只看未完成」这类过滤只存在于读取侧
  （N044），本 store 的任何路径都不因过滤删除记录。
"""

import json
import math
import sqlite3
import uuid
from typing import Any

from lumirss.db_tx import transaction
from lumirss.itemref import InvalidItemRef, parse_item_ref
from lumirss.storage import Database
from lumirss.util import utc_now

# 预算（分钟）边界；默认值与 F014 面板常用档位对齐。
_MIN_BUDGET_MINUTES = 5
_MAX_BUDGET_MINUTES = 480
_DEFAULT_BUDGET_MINUTES = 30

# 服务器侧估读速度：字符/分钟（有意粗估，见模块 docstring）。
_CHARS_PER_MINUTE = 400

# 单日队列硬上限（预算失控时的兜底，不是常规路径）。
_MAX_QUEUE_ITEMS = 100

_MAX_SNAPSHOTS = 50
_PAYLOAD_VERSION = 1

_MAX_SEGMENT_LENGTH = 60
_MAX_LABEL_LENGTH = 100

_QUEUE_SOURCES = ("manual", "budget", "level", "recovery")
_QUEUE_STATUSES = ("pending", "done", "removed")

# N046：可手动加入的来源（budget/level 只属于生成管线）。
_MANUAL_SOURCES = ("manual", "recovery")

# N046：冲突提示列表上限（诚实有界；超出部分以 truncated 标注）。
_MAX_CONFLICTS = 100


class QueueInvalid(Exception):
    """载荷非法（段名/快照名等）——400 invalid_queue。"""


class QueueItemNotFound(Exception):
    """队列项不存在（或不属于今天）——404 queue_item_not_found。"""


class QueueItemDone(Exception):
    """条目今天已完成，需先显式取消完成才能重新加入——409 queue_item_done。"""


class QueueSnapshotNotFound(Exception):
    """冻结快照不存在——404 queue_snapshot_not_found。"""


class QueueSnapshotLimit(Exception):
    """快照数达到上限——400 queue_snapshot_limit。"""


class QueueRevisionConflict(Exception):
    """N046：客户端 expectedRevision 落后于服务端——409。

    响应体额外携带 currentRevision 与逐 ref 的差异提示
    （conflicts: [{ref, serverItem, yourItem}]；yourItem 为 null 表示
    客户端没有该行的本地视图）。客户端「按项合并」逐条选择
    keep-mine / keep-theirs 后经 merge 提交。"""

    def __init__(
        self,
        current_revision: int,
        conflicts: list[dict[str, Any]],
        message: str | None = None,
    ) -> None:
        self.current_revision = current_revision
        self.conflicts = conflicts
        super().__init__(
            message
            or "队列已被其他设备修改：请逐项选择保留服务端还是本地的状态。"
        )


def today_queue_date() -> str:
    """服务端 UTC 日期（YYYY-MM-DD）——跨设备共享同一个「今天」。"""
    return utc_now()[:10]


def estimate_minutes(content_text: str | None) -> int:
    """服务器侧粗估读时：``max(1, ceil(len/400))``；无文本按 1 分钟。

    有意与 Web 侧 CJK 感知估算（lib/reading-time.ts）不同源：服务端只
    有投影纯文本，这里的目标是「一致、可解释」，不是精确。
    """
    length = len(content_text) if content_text else 0
    if length == 0:
        return 1
    return max(1, math.ceil(length / _CHARS_PER_MINUTE))


def _clean_segment(segment: str | None) -> str | None:
    """段名规范化：空白/越界拒绝；None = 未分组。"""
    if segment is None:
        return None
    if not isinstance(segment, str):
        raise QueueInvalid("segment 必须是字符串或 null。")
    clean = segment.strip()
    if not clean:
        raise QueueInvalid("segment 不能是空字符串（未分组请传 null）。")
    if len(clean) > _MAX_SEGMENT_LENGTH:
        raise QueueInvalid(f"segment 最长 {_MAX_SEGMENT_LENGTH} 字符。")
    return clean


class ReadingQueueStore:
    """Persistence for reading_queue / reading_queue_meta / queue_snapshots."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # -- reads ---------------------------------------------------------------

    async def today_rows(self, queue_date: str | None = None) -> list[dict[str, Any]]:
        """今天的队列行（pending + done，按 position；removed 不出库门，
        但行本身保留在库里——过滤绝不删除记录）。"""
        await self._db.migrate()
        day = queue_date or today_queue_date()
        rows = await self._db.fetch_all(
            "SELECT q.id, q.entry_ref, q.added_at, q.position, q.queue_date,"
            " q.source, q.status, q.segment, se.title AS projection_title,"
            " se.content_text AS projection_text"
            " FROM reading_queue q"
            " LEFT JOIN search_entries se ON se.entry_ref = substr(q.entry_ref, 5)"
            " WHERE q.queue_date = ? AND q.status != 'removed'"
            " ORDER BY q.position ASC, q.rowid ASC",
            (day,),
        )
        return [self._row_view(row) for row in rows]

    async def today_view(self) -> dict[str, Any]:
        """GET 视图：平铺 items + 派生 segments + 段顺序 + 估读合计。"""
        items = await self.today_rows()
        segment_order = await self._stored_segment_order()
        return {
            "queueDate": today_queue_date(),
            "items": items,
            "segments": self._derive_segments(items, segment_order),
            "segmentOrder": segment_order,
            "totalEstimateMinutes": self._total_estimate(items),
            "revision": await self.current_revision(),
        }

    # -- N046 revision guard ---------------------------------------------------

    async def current_revision(self, queue_date: str | None = None) -> int:
        """当前队列修订号（meta 行不存在 = 0；只增不减）。"""
        await self._db.migrate()
        day = queue_date or today_queue_date()
        row = await self._db.fetch_one(
            "SELECT queue_revision FROM reading_queue_meta WHERE queue_date = ?",
            (day,),
        )
        if row is None or row["queue_revision"] is None:
            return 0
        return int(row["queue_revision"])

    async def _bump_revision(self, queue_date: str | None = None) -> int:
        day = queue_date or today_queue_date()
        await self._db.execute(
            "INSERT INTO reading_queue_meta (queue_date, segment_order_json, queue_revision)"
            " VALUES (?, '[]', 1)"
            " ON CONFLICT(queue_date) DO UPDATE SET"
            " queue_revision = queue_revision + 1",
            (day,),
        )
        return await self.current_revision(day)

    @staticmethod
    def _bump_revision_tx(conn: sqlite3.Connection, queue_date: str) -> None:
        """事务内修订号 +1（meta 行懒创建；与既有行同语句原子生效）。"""
        conn.execute(
            "INSERT INTO reading_queue_meta (queue_date, segment_order_json, queue_revision)"
            " VALUES (?, '[]', 1)"
            " ON CONFLICT(queue_date) DO UPDATE SET"
            " queue_revision = queue_revision + 1",
            (queue_date,),
        )

    @staticmethod
    def _check_revision(
        expected_revision: int | None,
        current_revision: int,
        client_items: list[dict[str, Any]] | None,
        server_items: list[dict[str, Any]],
    ) -> None:
        """expectedRevision 给定且落后 → 抛 QueueRevisionConflict。

        差异提示逐 ref 计算：服务端行与客户端本地视图（按 id 匹配）
        的 status/segment 不一致，或客户端缺该行视图（yourItem=null）。
        未传 client_items 时只给 serverItem（yourItem=null），差异提示
        退化为「服务端现状」——客户端仍可整页重取或仅凭 ref 合并。"""
        if expected_revision is None or expected_revision == current_revision:
            return
        by_id = {str(item["id"]): item for item in (client_items or [])}
        conflicts: list[dict[str, Any]] = []
        for server in server_items:
            mine = by_id.get(str(server["id"]))
            if mine is not None and (
                mine.get("status") == server["status"]
                and mine.get("segment") == server["segment"]
            ):
                continue
            conflicts.append(
                {
                    "ref": server["itemRef"],
                    "serverItem": {
                        "id": server["id"],
                        "itemRef": server["itemRef"],
                        "status": server["status"],
                        "segment": server["segment"],
                        "position": server["position"],
                        "title": server["title"],
                    },
                    "yourItem": (
                        {
                            "id": str(mine["id"]),
                            "itemRef": str(mine.get("itemRef") or server["itemRef"]),
                            "status": str(mine.get("status") or "pending"),
                            "segment": mine.get("segment"),
                            "position": mine.get("position"),
                            "title": mine.get("title"),
                        }
                        if mine is not None
                        else None
                    ),
                }
            )
            if len(conflicts) >= _MAX_CONFLICTS:
                break
        raise QueueRevisionConflict(current_revision, conflicts)

    @staticmethod
    def _total_estimate(items: list[dict[str, Any]]) -> int:
        return sum(
            item["estimateMinutes"] or 0
            for item in items
            if item["status"] == "pending"
        )

    @staticmethod
    def _row_view(row: Any) -> dict[str, Any]:
        text = row["projection_text"]
        return {
            "id": str(row["id"]),
            "itemRef": str(row["entry_ref"]),
            "addedAt": str(row["added_at"]),
            "position": int(row["position"]),
            "queueDate": str(row["queue_date"]),
            "source": str(row["source"]),
            "status": str(row["status"]),
            "segment": row["segment"],
            # 呈现数据来自投影 best-effort：无投影行（条目已删除/退订、
            # 或 library ref）为 None → Web 呈现诚实占位。
            "title": row["projection_title"],
            "estimateMinutes": estimate_minutes(text) if text is not None else None,
        }

    @staticmethod
    def _derive_segments(
        items: list[dict[str, Any]], segment_order: list[str]
    ) -> list[dict[str, Any]]:
        """派生分段：未分组（None）恒为隐式前置组；其余按 meta 顺序，
        meta 没有的段名按成员首现顺序垫后；空段不出现在响应里。"""
        grouped: dict[str | None, list[dict[str, Any]]] = {}
        for item in items:
            grouped.setdefault(item["segment"], []).append(item)
        ordered_names: list[str | None] = [None]
        seen = {None}
        for name in segment_order:
            if name not in seen:
                ordered_names.append(name)
                seen.add(name)
        for item in items:
            name = item["segment"]
            if name not in seen:
                ordered_names.append(name)
                seen.add(name)
        return [
            {"name": name, "items": grouped[name]}
            for name in ordered_names
            if name in grouped
        ]

    async def _stored_segment_order(self, queue_date: str | None = None) -> list[str]:
        day = queue_date or today_queue_date()
        row = await self._db.fetch_one(
            "SELECT segment_order_json FROM reading_queue_meta WHERE queue_date = ?",
            (day,),
        )
        if row is None:
            return []
        try:
            parsed = json.loads(str(row["segment_order_json"]))
        except ValueError:
            return []
        if not isinstance(parsed, list):
            return []
        return [str(name) for name in parsed if isinstance(name, str)]

    # -- N041 generate ---------------------------------------------------------

    async def generate(
        self,
        *,
        budget_minutes: int | None = None,
        workspace_id: str | None = None,
        force: bool = False,
        levels: list[str] | None = None,
    ) -> dict[str, Any]:
        """生成（或幂等返回）今天的队列；返回 today_view + generated 等元数据。

        N020（已接线）：候选按来源关注级别排序——must_read 优先，其次
        normal（未设置级别 = normal），low 垫后（同级内仍按
        published_at recency 降序）；``levels`` 非空时把候选池限定到
        指定级别（normal = 未设置级别）。预算上限仍用粗估读时
        ``minutes = max(1, ceil(len(content_text) / 400))``，响应以
        ``basis``/``notes`` 字段诚实标注。若一个候选都装不下且确有
        未读，收进最近一篇（宁可超预算也不交空队列，诚实于「budget
        是估算」）。"""
        await self._db.migrate()
        day = today_queue_date()
        effective_budget = _DEFAULT_BUDGET_MINUTES if budget_minutes is None else budget_minutes
        existing = await self._db.fetch_all(
            "SELECT id FROM reading_queue WHERE queue_date = ? AND status != 'removed'",
            (day,),
        )
        if existing and not force:
            view = await self.today_view()
            view.update({"generated": False, "force": False, "basis": "existing"})
            return view

        kept_done: list[str] = []
        if force:
            # force 重建：pending 清掉重装；done 原样保留（完成按条目身份
            # 记账）；removed 墓碑保留——被手动移除的条目绝不因重建复活。
            # 候选排除 done ∪ removed。
            kept_rows = await self._db.fetch_all(
                "SELECT entry_ref, status FROM reading_queue WHERE queue_date = ?"
                " AND status != 'pending'",
                (day,),
            )
            kept_done = [
                str(row["entry_ref"])
                for row in kept_rows
                if row["status"] in ("done", "removed")
            ]

            def _tx(conn: sqlite3.Connection) -> None:
                conn.execute(
                    "DELETE FROM reading_queue WHERE queue_date = ? AND status = 'pending'",
                    (day,),
                )

            await transaction(self._db, _tx)

        candidates = await self._candidate_rows(
            budget_minutes=effective_budget,
            workspace_id=workspace_id,
            excluded_refs=kept_done,
            levels=levels,
        )
        if candidates:
            await self._insert_generated(day, candidates)
        view = await self.today_view()
        view.update(
            {
                "generated": True,
                "force": force,
                "basis": "unread+attention-level+recency" if levels else "unread+recency",
                "budgetMinutes": effective_budget,
            }
        )
        if levels:
            view["notes"] = [
                f"levels={','.join(levels)}：候选池已限定到指定关注级别"
                "（normal = 未设置级别）。",
            ]
        return view

    async def _candidate_rows(
        self,
        *,
        budget_minutes: int,
        workspace_id: str | None,
        excluded_refs: list[str],
        levels: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """候选：未读 + 关注级别排序（must_read → normal → low）+ 近期。

        - 级别来自 source_overrides.attention_level（N020；NULL = normal），
          LEFT JOIN 服务端排序，同级内按 published_at DESC；
        - ``levels``（N020）非空时候选池限定到指定级别（HAVING 语义，
          无匹配行不报错）；装不下的候选跳过（更近但很长的文不挡后面
          短文，语义同 F014）；
        - 全都装不下且确有候选 → 收最近一篇（宁可超预算，不交空队列）；
        - workspace_id 提供时，候选限定为该工作区成员（ItemRef 同构）。
        """
        params: list[Any] = []
        where_extra = ""
        if workspace_id is not None:
            where_extra = (
                " AND EXISTS (SELECT 1 FROM workspace_items w"
                " WHERE w.workspace_id = ? AND w.item_ref = 'rss:' || s.entry_ref)"
            )
            params.append(workspace_id)
        level_filter = ""
        if levels:
            clean = [level for level in levels if level in ("must_read", "normal", "low")]
            if clean:
                placeholders = ",".join("?" for _ in clean)
                level_filter = (
                    f" AND COALESCE(so.attention_level, 'normal') IN ({placeholders})"
                )
                params.extend(clean)
        rows = await self._db.fetch_all(
            "SELECT s.entry_ref, s.title, s.content_text FROM search_entries s"
            " LEFT JOIN source_overrides so ON so.feed_url = s.feed_url"
            " WHERE s.read = 0" + where_extra + level_filter +
            " ORDER BY CASE COALESCE(so.attention_level, 'normal')"
            " WHEN 'must_read' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,"
            " s.published_at DESC, s.id DESC"
            " LIMIT 500",
            tuple(params),
        )
        excluded = set(excluded_refs)
        picked: list[dict[str, Any]] = []
        used = 0
        for row in rows:
            ref = f"rss:{row['entry_ref']}"
            if ref in excluded:
                continue
            minutes = estimate_minutes(row["content_text"])
            if len(picked) >= _MAX_QUEUE_ITEMS:
                break
            if used + minutes > budget_minutes:
                continue
            picked.append(
                {"ref": ref, "minutes": minutes, "title": row["title"]}
            )
            used += minutes
        if not picked and rows:
            # 预算装不下任何候选：收最近一篇（诚实标注为估算超支）。
            first = rows[0]
            picked.append(
                {
                    "ref": f"rss:{first['entry_ref']}",
                    "minutes": estimate_minutes(first["content_text"]),
                    "title": first["title"],
                }
            )
        return picked

    async def _insert_generated(self, day: str, candidates: list[dict[str, Any]]) -> None:
        now = utc_now()

        def _tx(conn: sqlite3.Connection) -> None:
            next_position = conn.execute(
                "SELECT COALESCE(MAX(position), 0) FROM reading_queue WHERE queue_date = ?",
                (day,),
            ).fetchone()[0]
            for candidate in candidates:
                next_position += 1
                conn.execute(
                    "INSERT INTO reading_queue (id, entry_ref, added_at, position,"
                    " queue_date, source, status, segment) VALUES (?, ?, ?, ?, ?, 'budget', 'pending', NULL)",
                    (f"rq-{uuid.uuid4().hex}", candidate["ref"], now, next_position, day),
                )
            self._bump_revision_tx(conn, day)

        await transaction(self._db, _tx)

    # -- N041 manual add / remove / done / reorder -----------------------------

    async def add_item(
        self,
        item_ref: str,
        segment: str | None = None,
        *,
        source: str = "manual",
        expected_revision: int | None = None,
        client_items: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], str]:
        """手动加入（source=manual；N037 补读走 source=recovery）。返回
        (视图, 结果)。

        - 新加入 → ``created``（201）；
        - 今天已存在 pending 行 → ``duplicate``（幂等返回，绝不重排）；
        - 今天已被移除（removed）→ ``resurrected``（显式重新加入，
          垫到队尾）；
        - 今天已完成（done）→ 抛 QueueItemDone（409；先取消完成再加）。

        N046：``expected_revision`` 给定且落后 → 409
        QueueRevisionConflict（先于任何写入发生——冲突绝不半途落库）。
        """
        await self._db.migrate()
        if source not in _MANUAL_SOURCES:
            raise QueueInvalid(f"source 必须是 {' 或 '.join(_MANUAL_SOURCES)}。")
        clean_segment = _clean_segment(segment)
        try:
            parse_item_ref(item_ref)
        except InvalidItemRef as exc:
            raise QueueInvalid(f"itemRef 不合法：{exc}") from exc
        day = today_queue_date()
        existing = await self._db.fetch_one(
            "SELECT id, status FROM reading_queue WHERE queue_date = ? AND entry_ref = ?",
            (day, item_ref),
        )
        if existing is None:
            # 新行：先做修订守卫（仅当确要写入时）。
            await self._guard_revision(expected_revision, client_items, day)
        if existing is not None:
            if existing["status"] == "pending":
                row = await self._get_row(str(existing["id"]))
                return row, "duplicate"
            if existing["status"] == "done":
                raise QueueItemDone(
                    "该条目今日已完成：请先取消完成状态，再重新加入队列。"
                )
            # removed → 显式复活（垫到队尾，回到 pending）。
            await self._db.execute(
                "UPDATE reading_queue SET status = 'pending', segment = ?,"
                " added_at = ?, position = (SELECT COALESCE(MAX(position), 0) + 1"
                "  FROM reading_queue WHERE queue_date = ?)"
                " WHERE id = ?",
                (clean_segment, utc_now(), day, str(existing["id"])),
            )
            await self._bump_revision(day)
            row = await self._get_row(str(existing["id"]))
            return row, "resurrected"

        count_row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM reading_queue WHERE queue_date = ?", (day,)
        )
        if count_row is not None and int(count_row["n"]) >= _MAX_QUEUE_ITEMS:
            raise QueueInvalid(f"今天的队列已满（上限 {_MAX_QUEUE_ITEMS} 条）。")
        item_id = f"rq-{uuid.uuid4().hex}"
        await self._db.execute(
            "INSERT INTO reading_queue (id, entry_ref, added_at, position, queue_date,"
            " source, status, segment) VALUES (?, ?, ?,"
            " (SELECT COALESCE(MAX(position), 0) + 1 FROM reading_queue WHERE queue_date = ?),"
            " ?, ?, 'pending', ?)",
            (item_id, item_ref, utc_now(), day, day, source, clean_segment),
        )
        await self._bump_revision(day)
        row = await self._get_row(item_id)
        return row, "created"

    async def _guard_revision(
        self,
        expected_revision: int | None,
        client_items: list[dict[str, Any]] | None,
        day: str,
    ) -> None:
        if expected_revision is None:
            return
        current = await self.current_revision(day)
        if expected_revision == current:
            return
        server_items = await self._conflict_rows(day)
        self._check_revision(expected_revision, current, client_items, server_items)

    async def _conflict_rows(self, day: str) -> list[dict[str, Any]]:
        """冲突差异提示用的全量行（含 removed——「另一端已移除」同样是
        客户端需要看到的差异；正式视图不出 removed 行）。"""
        rows = await self._db.fetch_all(
            "SELECT q.id, q.entry_ref, q.added_at, q.position, q.queue_date,"
            " q.source, q.status, q.segment, se.title AS projection_title,"
            " se.content_text AS projection_text"
            " FROM reading_queue q"
            " LEFT JOIN search_entries se ON se.entry_ref = substr(q.entry_ref, 5)"
            " WHERE q.queue_date = ?"
            " ORDER BY q.position ASC, q.rowid ASC",
            (day,),
        )
        return [self._row_view(row) for row in rows]

    async def _get_row(self, item_id: str) -> dict[str, Any]:
        row = await self._db.fetch_one(
            "SELECT q.id, q.entry_ref, q.added_at, q.position, q.queue_date,"
            " q.source, q.status, q.segment, se.title AS projection_title,"
            " se.content_text AS projection_text"
            " FROM reading_queue q"
            " LEFT JOIN search_entries se ON se.entry_ref = substr(q.entry_ref, 5)"
            " WHERE q.id = ?",
            (item_id,),
        )
        if row is None or row["status"] == "removed":
            raise QueueItemNotFound(item_id)
        return self._row_view(row)

    async def remove_item(
        self,
        item_id: str,
        *,
        expected_revision: int | None = None,
        client_items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """移除（status=removed，行保留——生成绝不复活被移除的条目）。"""
        await self._db.migrate()
        view = await self._get_row(item_id)
        await self._guard_revision(expected_revision, client_items, view["queueDate"])

        def _tx(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE reading_queue SET status = 'removed' WHERE id = ?", (item_id,)
            )
            # 剩余行位置压实（保持相对顺序），position 恒为 1..n。
            rows = conn.execute(
                "SELECT id FROM reading_queue WHERE queue_date = ? AND status != 'removed'"
                " ORDER BY position ASC, rowid ASC",
                (view["queueDate"],),
            ).fetchall()
            for index, row in enumerate(rows, start=1):
                conn.execute(
                    "UPDATE reading_queue SET position = ? WHERE id = ?",
                    (index, row[0]),
                )
            self._bump_revision_tx(conn, view["queueDate"])

        await transaction(self._db, _tx)
        return view

    async def set_item_done(
        self,
        item_id: str,
        done: bool,
        *,
        expected_revision: int | None = None,
        client_items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """完成状态（set 语义，按条目身份记账；绝不隐式改写上游已读）。"""
        await self._db.migrate()
        row = await self._get_row(item_id)
        await self._guard_revision(expected_revision, client_items, row["queueDate"])
        status = "done" if done else "pending"
        await self._db.execute(
            "UPDATE reading_queue SET status = ? WHERE id = ?", (status, item_id)
        )
        await self._bump_revision(row["queueDate"])
        return await self._get_row(item_id)

    async def reorder(
        self,
        item_ids: list[str],
        *,
        expected_revision: int | None = None,
        client_items: list[dict[str, Any]] | None = None,
    ) -> None:
        """持久化重排：给定 id 按 1..k 排列，未提及的非 removed 行保持
        当前相对顺序垫在后面（语义同工作区 reorder）。"""
        await self._db.migrate()
        day = today_queue_date()
        await self._guard_revision(expected_revision, client_items, day)

        def _tx(conn: sqlite3.Connection) -> None:
            rows = conn.execute(
                "SELECT id FROM reading_queue WHERE queue_date = ? AND status != 'removed'"
                " ORDER BY position ASC, rowid ASC",
                (day,),
            ).fetchall()
            known = [str(row[0]) for row in rows]
            known_set = set(known)
            requested = [item_id for item_id in item_ids if item_id in known_set]
            tail = [item_id for item_id in known if item_id not in set(requested)]
            for index, row_id in enumerate(requested + tail, start=1):
                conn.execute(
                    "UPDATE reading_queue SET position = ? WHERE id = ? AND queue_date = ?",
                    (index, row_id, day),
                )
            self._bump_revision_tx(conn, day)

        await transaction(self._db, _tx)

    # -- N042 segments ---------------------------------------------------------

    async def set_item_segment(
        self,
        item_id: str,
        segment: str | None,
        *,
        expected_revision: int | None = None,
        client_items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """行菜单移动分段（N042）；新段名随行诞生（派生语义，无段表）。"""
        await self._db.migrate()
        clean = _clean_segment(segment)
        row = await self._get_row(item_id)
        await self._guard_revision(expected_revision, client_items, row["queueDate"])
        await self._db.execute(
            "UPDATE reading_queue SET segment = ? WHERE id = ?", (clean, item_id)
        )
        await self._bump_revision(row["queueDate"])
        if clean is not None:
            await self._append_segment_names([clean])
        return await self._get_row(item_id)

    # -- N046 按项合并 ----------------------------------------------------------

    async def merge_conflicts(
        self,
        expected_revision: int,
        resolutions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """按项合并：逐冲突 ref 显式选择 keep-mine（应用客户端状态）或
        keep-theirs（保持服务端现状）。修订号必须与 current 一致（否则
        再 409）；合并整体 bump 一次修订号。返回合并后的今日视图。

        keep-mine 应用字段 = status + segment（位置顺序不属于本冲突
        语义——两端重排以最后写入为准，无 per-item 内容差异可解）。"""
        day = today_queue_date()
        current = await self.current_revision(day)
        if expected_revision != current:
            server_items = await self._conflict_rows(day)
            self._check_revision(expected_revision, current, None, server_items)
        applied = 0
        for resolution in resolutions:
            action = resolution.get("action")
            ref = resolution.get("itemRef")
            if action not in ("keep-mine", "keep-theirs") or not isinstance(ref, str):
                raise QueueInvalid("resolution 必须是 {itemRef, action: keep-mine|keep-theirs}。")
            if action == "keep-theirs":
                continue
            client_item = resolution.get("clientItem")
            if not isinstance(client_item, dict):
                raise QueueInvalid("keep-mine 需要 clientItem（本地状态视图）。")
            row = await self._db.fetch_one(
                "SELECT id, status FROM reading_queue WHERE queue_date = ? AND entry_ref = ?",
                (day, ref),
            )
            if row is None:
                continue  # 服务端无此行：keep-mine 无处可落，诚实跳过
            status = client_item.get("status")
            if status not in _QUEUE_STATUSES:
                status = str(row["status"])
            segment = client_item.get("segment")
            clean_segment = (
                _clean_segment(segment) if segment is not None else None
            )
            if row["status"] == "removed" and status != "removed":
                # keep-mine 复活被另一端移除的行（垫到队尾，语义同
                # add_item 的显式复活）。
                await self._db.execute(
                    "UPDATE reading_queue SET status = ?, segment = ?,"
                    " added_at = ?, position = (SELECT COALESCE(MAX(position), 0) + 1"
                    "  FROM reading_queue WHERE queue_date = ?)"
                    " WHERE id = ?",
                    (status, clean_segment, utc_now(), day, str(row["id"])),
                )
            else:
                await self._db.execute(
                    "UPDATE reading_queue SET status = ?, segment = ? WHERE id = ?",
                    (status, clean_segment, str(row["id"])),
                )
            applied += 1
        if applied > 0:
            await self._bump_revision(day)
        view = await self.today_view()
        view["merge"] = {"applied": applied, "resolutions": len(resolutions)}
        return view

    async def set_segment_order(self, names: list[str]) -> list[str]:
        """段顺序（呈现提示；meta 行懒创建——N101 group_order_json 同构）。"""
        await self._db.migrate()
        cleaned: list[str] = []
        for name in names:
            clean = _clean_segment(name)
            if clean is not None and clean not in cleaned:
                cleaned.append(clean)
        await self._db.execute(
            "INSERT INTO reading_queue_meta (queue_date, segment_order_json) VALUES (?, ?)"
            " ON CONFLICT(queue_date) DO UPDATE SET segment_order_json = excluded.segment_order_json",
            (today_queue_date(), json.dumps(cleaned, ensure_ascii=False)),
        )
        return cleaned

    async def _append_segment_names(self, names: list[str]) -> None:
        stored = await self._stored_segment_order()
        merged = list(stored)
        for name in names:
            if name not in merged:
                merged.append(name)
        if merged != stored:
            await self.set_segment_order(merged)

    # -- N043 freeze -----------------------------------------------------------

    async def freeze(self, label: str) -> dict[str, Any]:
        """把当前 pending 成员冻结为不可变快照（201）。

        - 只冻结 pending（done 是历史，不是待读批次）；
        - payload 只带 ItemRef + position + segment，绝不复制内容；
        - 冻结后新加入的项绝不进入旧快照（快照不可变，无任何写路径）。
        """
        await self._db.migrate()
        clean_label = _validate_label(label)
        day = today_queue_date()
        count_row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM queue_snapshots WHERE queue_date = ?", (day,)
        )
        if count_row is not None and int(count_row["n"]) >= _MAX_SNAPSHOTS:
            raise QueueSnapshotLimit(f"快照数已达上限（{_MAX_SNAPSHOTS}）。")
        items = [
            item
            for item in await self.today_rows()
            if item["status"] == "pending"
        ]
        segment_order = await self._stored_segment_order(day)
        payload = {
            "version": _PAYLOAD_VERSION,
            "items": [
                {
                    "item_ref": item["itemRef"],
                    "position": item["position"],
                    "segment": item["segment"],
                }
                for item in items
            ],
            "segment_order": segment_order,
        }
        snapshot_id = f"qsnap-{uuid.uuid4().hex}"
        created_at = utc_now()
        await self._db.execute(
            "INSERT INTO queue_snapshots (id, label, queue_date, created_at, payload_json)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                snapshot_id,
                clean_label,
                day,
                created_at,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        return {
            "id": snapshot_id,
            "label": clean_label,
            "queueDate": day,
            "createdAt": created_at,
            "itemCount": len(items),
        }

    async def list_snapshots(self) -> list[dict[str, Any]]:
        """快照列表（新→旧；rowid = 诚实捕获顺序，同 N105）。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, label, queue_date, created_at, payload_json"
            " FROM queue_snapshots ORDER BY rowid DESC"
        )
        return [self._snapshot_meta(row) for row in rows]

    async def get_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        """打开冻结视图：原始成员顺序原样返回；ref 消失由 Web 以解析
        状态诚实呈现占位（服务端绝不复活、绝不补内容）。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, label, queue_date, created_at, payload_json"
            " FROM queue_snapshots WHERE id = ?",
            (snapshot_id,),
        )
        if row is None:
            raise QueueSnapshotNotFound(snapshot_id)
        try:
            payload = json.loads(str(row["payload_json"]))
        except ValueError as exc:
            raise QueueInvalid("快照 payload 不是合法 JSON。") from exc
        raw_items = payload.get("items") if isinstance(payload, dict) else None
        items = []
        for entry in raw_items if isinstance(raw_items, list) else []:
            if not isinstance(entry, dict) or not isinstance(entry.get("item_ref"), str):
                continue
            items.append(
                {
                    "itemRef": str(entry["item_ref"]),
                    "position": int(entry.get("position", 0)),
                    "segment": (
                        entry["segment"]
                        if isinstance(entry.get("segment"), str)
                        else None
                    ),
                }
            )
        items.sort(key=lambda item: item["position"])
        raw_order = payload.get("segment_order") if isinstance(payload, dict) else None
        segment_order = (
            [str(name) for name in raw_order if isinstance(name, str)]
            if isinstance(raw_order, list)
            else []
        )
        return {
            "id": str(row["id"]),
            "label": str(row["label"]),
            "queueDate": str(row["queue_date"]),
            "createdAt": str(row["created_at"]),
            "items": items,
            "segmentOrder": segment_order,
        }

    async def delete_snapshot(self, snapshot_id: str) -> bool:
        """删除快照（false = 不存在）。"""
        await self._db.migrate()

        def _tx(conn: sqlite3.Connection) -> bool:
            cursor = conn.execute(
                "DELETE FROM queue_snapshots WHERE id = ?", (snapshot_id,)
            )
            return cursor.rowcount > 0

        return await transaction(self._db, _tx)

    @staticmethod
    def _snapshot_meta(row: Any) -> dict[str, Any]:
        try:
            payload = json.loads(str(row["payload_json"]))
        except ValueError:
            payload = {}
        items = payload.get("items") if isinstance(payload, dict) else None
        return {
            "id": str(row["id"]),
            "label": str(row["label"]),
            "queueDate": str(row["queue_date"]),
            "createdAt": str(row["created_at"]),
            "itemCount": len(items) if isinstance(items, list) else 0,
        }


def _validate_label(label: str) -> str:
    """快照名与工作区名同界（非空、去首尾空白、≤100 字符）。"""
    if not isinstance(label, str):
        raise QueueInvalid("label 必须是字符串。")
    clean = label.strip()
    if not clean:
        raise QueueInvalid("label 不能为空。")
    if len(clean) > _MAX_LABEL_LENGTH:
        raise QueueInvalid(f"label 最长 {_MAX_LABEL_LENGTH} 字符。")
    return clean
