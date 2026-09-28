"""NEW-222 队列依赖关系 —— 为阅读材料设置先读项（先读 A 再读 B）。

- 依赖是建议性元数据：``GET view`` 逐条报告前置是否已满足（met），
  ``unmetCount`` 供面板展示；服务端**没有任何路径**因依赖未满足而
  拒绝打开/完成/移除材料——「不强制阻止跳读」是硬边界；
- met 的判定基础（诚实多源，逐条标注 basis）：
  ``read``      = 上游投影已读（search_entries.read=1，FreshRSS 域）；
  ``queue-done``= 今天必读队列中该条目已完成（reading_queue done）；
  ``slot-done`` = 分时段队列中已完成（NEW-221 done）；
  ``unknown``   = 无投影且无队列行（如 library ref 无上游状态）；
- 环检测：加入 item→prereq 前沿 prereq 出发 BFS，若能回到 item 则
  拒绝（依赖图保持 DAG；跳读不受影响，只是不让依赖自指）。
"""

import uuid
from typing import Any

from lumirss.itemref import InvalidItemRef, parse_item_ref
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_PER_ITEM = 20
_MAX_TOTAL = 500


class PrereqInvalid(Exception):
    """依赖载荷非法（自指/成环/非法 ref/超限）——422 invalid_queue_prereq。"""


class PrereqNotFound(Exception):
    """依赖关系不存在——404 queue_prereq_not_found。"""


def validate_ref(value: str) -> str:
    try:
        parse_item_ref(value)
    except InvalidItemRef as exc:
        raise PrereqInvalid(f"itemRef 不合法：{exc}") from exc
    return value


class PrereqStore:
    """Persistence for queue_prereqs."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # -- write -----------------------------------------------------------------

    async def add_prereq(self, item_ref: str, prereq_ref: str) -> tuple[dict[str, Any], str]:
        """设置先读项（新 201 / 重复 → duplicate 200）。自指/成环 → 422。"""
        await self._db.migrate()
        validate_ref(item_ref)
        validate_ref(prereq_ref)
        if item_ref == prereq_ref:
            raise PrereqInvalid("先读项不能是材料本身。")
        if await self._reaches(prereq_ref, item_ref):
            raise PrereqInvalid(
                "这条依赖会形成环（该先读项已经（直接或间接）依赖本材料）。"
            )
        count = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM queue_prereqs"
            " WHERE item_ref = ?",
            (item_ref,),
        )
        if count is not None and int(count["n"]) >= _MAX_PER_ITEM:
            raise PrereqInvalid(f"每个材料的先读项上限 {_MAX_PER_ITEM} 条。")
        total = await self._db.fetch_one("SELECT COUNT(*) AS n FROM queue_prereqs")
        if total is not None and int(total["n"]) >= _MAX_TOTAL:
            raise PrereqInvalid(f"依赖关系总量上限 {_MAX_TOTAL} 条。")
        existing = await self._db.fetch_one(
            "SELECT id FROM queue_prereqs WHERE item_ref = ? AND prereq_ref = ?",
            (item_ref, prereq_ref),
        )
        if existing is not None:
            row = await self._row(str(existing["id"]))
            return row, "duplicate"
        prereq_id = f"qpre-{uuid.uuid4().hex}"
        await self._db.execute(
            "INSERT INTO queue_prereqs (id, item_ref, prereq_ref, created_at)"
            " VALUES (?, ?, ?, ?)",
            (prereq_id, item_ref, prereq_ref, utc_now()),
        )
        row = await self._row(prereq_id)
        return row, "created"

    async def _reaches(self, start_ref: str, target_ref: str) -> bool:
        """从 start 沿「材料 → 它的先读项」边 BFS，能否到达 target。"""
        frontier = [start_ref]
        seen = {start_ref}
        while frontier:
            rows = await self._db.fetch_all(
                "SELECT prereq_ref FROM queue_prereqs WHERE item_ref = ?",
                (frontier.pop(),),
            )
            for row in rows:
                nxt = str(row["prereq_ref"])
                if nxt == target_ref:
                    return True
                if nxt not in seen:
                    seen.add(nxt)
                    frontier.append(nxt)
        return False

    async def remove_prereq(self, prereq_id: str) -> None:
        await self._db.migrate()
        await self._row(prereq_id)  # 404 when missing
        await self._db.execute("DELETE FROM queue_prereqs WHERE id = ?", (prereq_id,))

    # -- read --------------------------------------------------------------------

    async def view_item(self, item_ref: str) -> dict[str, Any]:
        """材料的先读项视图：逐条 met/unmet（basis 标注），advisory only。"""
        await self._db.migrate()
        validate_ref(item_ref)
        rows = await self._db.fetch_all(
            "SELECT p.id, p.item_ref, p.prereq_ref, p.created_at,"
            " se.title AS projection_title, se.read AS upstream_read"
            " FROM queue_prereqs p"
            " LEFT JOIN search_entries se ON se.entry_ref = substr(p.prereq_ref, 5)"
            " WHERE p.item_ref = ? ORDER BY p.created_at ASC, p.rowid ASC",
            (item_ref,),
        )
        prereqs = []
        unmet = 0
        for row in rows:
            prereq_ref = str(row["prereq_ref"])
            met, basis = await self._met_status(prereq_ref, row["upstream_read"])
            if not met:
                unmet += 1
            prereqs.append(
                {
                    "id": str(row["id"]),
                    "prereqRef": prereq_ref,
                    "title": row["projection_title"],
                    "met": met,
                    "basis": basis,
                    "createdAt": str(row["created_at"]),
                }
            )
        return {
            "itemRef": item_ref,
            "prereqs": prereqs,
            "unmetCount": unmet,
            "advisory": True,
            "note": "依赖是建议性提示：未满足的前置阅读不会被阻止跳读。",
        }

    async def _met_status(self, prereq_ref: str, upstream_read: Any) -> tuple[bool, str]:
        if upstream_read is not None and int(upstream_read) == 1:
            return True, "read"
        row = await self._db.fetch_one(
            "SELECT status FROM reading_queue WHERE entry_ref = ? AND status = 'done'"
            " ORDER BY rowid DESC LIMIT 1",
            (prereq_ref,),
        )
        if row is not None:
            return True, "queue-done"
        row = await self._db.fetch_one(
            "SELECT status FROM queue_time_slot_items"
            " WHERE item_ref = ? AND status = 'done' LIMIT 1",
            (prereq_ref,),
        )
        if row is not None:
            return True, "slot-done"
        if upstream_read is None:
            return False, "unknown"
        return False, "unread"

    async def list_for_today_queue(self) -> dict[str, Any]:
        """今日队列成员的未满足前置汇总（整理时一览；纯读取）。"""
        day = utc_now()[:10]
        rows = await self._db.fetch_all(
            "SELECT q.entry_ref FROM reading_queue q"
            " WHERE q.queue_date = ? AND q.status != 'removed'",
            (day,),
        )
        summaries = []
        for row in rows:
            view = await self.view_item(str(row["entry_ref"]))
            if view["unmetCount"] > 0:
                summaries.append(
                    {"itemRef": view["itemRef"], "unmetCount": view["unmetCount"]}
                )
        return {"queueDate": day, "itemsWithUnmet": summaries}

    async def _row(self, prereq_id: str) -> dict[str, Any]:
        row = await self._db.fetch_one(
            "SELECT id, item_ref, prereq_ref, created_at FROM queue_prereqs"
            " WHERE id = ?",
            (prereq_id,),
        )
        if row is None:
            raise PrereqNotFound(prereq_id)
        return {
            "id": str(row["id"]),
            "itemRef": str(row["item_ref"]),
            "prereqRef": str(row["prereq_ref"]),
            "createdAt": str(row["created_at"]),
        }
