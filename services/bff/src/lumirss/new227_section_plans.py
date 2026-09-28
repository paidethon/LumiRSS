"""NEW-227 章节级阅读计划 —— 把长文的章节分配到几次阅读。

- 一篇长文一个计划（``section_plans.item_ref`` UNIQUE）；章节行
  （label + session_no）由用户定义——服务端绝不自动猜测章节边界
  （投影只有纯文本，没有可靠章节结构，诚实不猜）；
- 完成记账在**章节行**（status/done_at，set 语义）：进度 =
  doneSections/totalSections 的整数计数 + 每 session 的分桶——
  绝不只存「文章百分比」；
- session_no 是第几次阅读（1..52），可留空（未分配）。
"""

from typing import Any

import uuid

from lumirss.itemref import InvalidItemRef, parse_item_ref
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_SECTIONS = 100
_MAX_LABEL = 120
_MAX_SESSION = 52


class PlanInvalid(Exception):
    """计划/章节载荷非法——422 invalid_section_plan。"""


class PlanNotFound(Exception):
    """计划不存在——404 section_plan_not_found。"""


class PlanSectionNotFound(Exception):
    """章节不存在——404 section_plan_section_not_found。"""


class PlanConflict(Exception):
    """该材料已有计划（一篇一个）——409 section_plan_conflict。"""


def validate_ref(value: str) -> str:
    try:
        parse_item_ref(value)
    except InvalidItemRef as exc:
        raise PlanInvalid(f"itemRef 不合法：{exc}") from exc
    return value


def validate_label(label: str) -> str:
    if not isinstance(label, str):
        raise PlanInvalid("label 必须是字符串。")
    clean = label.strip()
    if not clean:
        raise PlanInvalid("label 不能为空。")
    if len(clean) > _MAX_LABEL:
        raise PlanInvalid(f"label 最长 {_MAX_LABEL} 字符。")
    return clean


def validate_session(session_no: int | None) -> int | None:
    if session_no is None:
        return None
    if not isinstance(session_no, int) or isinstance(session_no, bool):
        raise PlanInvalid("sessionNo 必须是整数或 null。")
    if not 1 <= session_no <= _MAX_SESSION:
        raise PlanInvalid(f"sessionNo 必须在 1..{_MAX_SESSION} 之间。")
    return session_no


class SectionPlanStore:
    """Persistence for section_plans / section_plan_sections."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create_plan(
        self, item_ref: str, sections: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """建计划（含章节清单）；一篇一个，重复 → 409 PlanConflict。"""
        await self._db.migrate()
        validate_ref(item_ref)
        if not isinstance(sections, list) or not (1 <= len(sections) <= _MAX_SECTIONS):
            raise PlanInvalid(f"sections 需为 1..{_MAX_SECTIONS} 个。")
        existing = await self._db.fetch_one(
            "SELECT id FROM section_plans WHERE item_ref = ?", (item_ref,)
        )
        if existing is not None:
            raise PlanConflict(item_ref)
        plan_id = f"splan-{uuid.uuid4().hex}"
        now = utc_now()
        prepared: list[tuple[str, int, str, int | None]] = []
        for index, section in enumerate(sections, start=1):
            if not isinstance(section, dict):
                raise PlanInvalid("sections 成员必须是对象。")
            label = validate_label(section.get("label"))
            session_no = validate_session(section.get("sessionNo"))
            prepared.append((f"ssec-{uuid.uuid4().hex}", index, label, session_no))
        from lumirss.db_tx import transaction

        def _tx(conn: Any) -> None:
            conn.execute(
                "INSERT INTO section_plans (id, item_ref, created_at, updated_at)"
                " VALUES (?, ?, ?, ?)",
                (plan_id, item_ref, now, now),
            )
            for section_id, position, label, session_no in prepared:
                conn.execute(
                    "INSERT INTO section_plan_sections (id, plan_id, position,"
                    " label, session_no, status) VALUES (?, ?, ?, ?, ?, 'pending')",
                    (section_id, plan_id, position, label, session_no),
                )

        await transaction(self._db, _tx)
        return await self.get_plan(item_ref)

    async def get_plan(self, item_ref: str) -> dict[str, Any]:
        """计划视图：章节 + 整数进度 + 分 session 桶（绝不只给百分比）。"""
        await self._db.migrate()
        validate_ref(item_ref)
        plan = await self._db.fetch_one(
            "SELECT id, item_ref, created_at, updated_at FROM section_plans"
            " WHERE item_ref = ?",
            (item_ref,),
        )
        if plan is None:
            raise PlanNotFound(item_ref)
        rows = await self._db.fetch_all(
            "SELECT id, position, label, session_no, status, done_at"
            " FROM section_plan_sections WHERE plan_id = ?"
            " ORDER BY position ASC",
            (str(plan["id"]),),
        )
        sections = [
            {
                "id": str(row["id"]),
                "position": int(row["position"]),
                "label": str(row["label"]),
                "sessionNo": row["session_no"],
                "status": str(row["status"]),
                "doneAt": row["done_at"],
            }
            for row in rows
        ]
        done = sum(1 for section in sections if section["status"] == "done")
        by_session: dict[str, dict[str, Any]] = {}
        for section in sections:
            key = str(section["sessionNo"]) if section["sessionNo"] is not None else "unassigned"
            bucket = by_session.setdefault(key, {"sessionNo": section["sessionNo"], "total": 0, "done": 0})
            bucket["total"] += 1
            if section["status"] == "done":
                bucket["done"] += 1
        return {
            "id": str(plan["id"]),
            "itemRef": str(plan["item_ref"]),
            "createdAt": str(plan["created_at"]),
            "updatedAt": str(plan["updated_at"]),
            "sections": sections,
            "progress": {
                "totalSections": len(sections),
                "doneSections": done,
                "pendingSections": len(sections) - done,
                "bySession": list(by_session.values()),
            },
        }

    async def update_section(
        self,
        section_id: str,
        *,
        label: str | None = None,
        session_no: int | None = None,
        clear_session: bool = False,
    ) -> dict[str, Any]:
        """改章节标签 / 分配到某一次阅读（或清除分配）。"""
        await self._db.migrate()
        row = await self._section(section_id)
        sets: list[str] = []
        params: list[Any] = []
        if label is not None:
            sets.append("label = ?")
            params.append(validate_label(label))
        if clear_session:
            sets.append("session_no = NULL")
        elif session_no is not None:
            sets.append("session_no = ?")
            params.append(validate_session(session_no))
        if sets:
            params.append(section_id)
            await self._db.execute(
                "UPDATE section_plan_sections SET " + ", ".join(sets) + " WHERE id = ?",
                tuple(params),
            )
            await self._db.execute(
                "UPDATE section_plans SET updated_at = ? WHERE id = ?",
                (utc_now(), str(row["plan_id"])),
            )
        return await self._section_view(section_id)

    async def set_section_done(self, section_id: str, done: bool) -> dict[str, Any]:
        """章节完成（set 语义；这就是「每次结束保存完成章节」）。"""
        await self._db.migrate()
        row = await self._section(section_id)
        await self._db.execute(
            "UPDATE section_plan_sections SET status = ?, done_at = ? WHERE id = ?",
            ("done" if done else "pending", utc_now() if done else None, section_id),
        )
        await self._db.execute(
            "UPDATE section_plans SET updated_at = ? WHERE id = ?",
            (utc_now(), str(row["plan_id"])),
        )
        return await self._section_view(section_id)

    async def delete_plan(self, item_ref: str) -> None:
        await self._db.migrate()
        plan = await self._db.fetch_one(
            "SELECT id FROM section_plans WHERE item_ref = ?", (item_ref,)
        )
        if plan is None:
            raise PlanNotFound(item_ref)
        from lumirss.db_tx import transaction

        def _tx(conn: Any) -> None:
            conn.execute(
                "DELETE FROM section_plan_sections WHERE plan_id = ?", (str(plan["id"]),)
            )
            conn.execute("DELETE FROM section_plans WHERE id = ?", (str(plan["id"]),))

        await transaction(self._db, _tx)

    async def _section(self, section_id: str) -> dict[str, Any]:
        row = await self._db.fetch_one(
            "SELECT id, plan_id FROM section_plan_sections WHERE id = ?",
            (section_id,),
        )
        if row is None:
            raise PlanSectionNotFound(section_id)
        return {"id": str(row["id"]), "plan_id": str(row["plan_id"])}

    async def _section_view(self, section_id: str) -> dict[str, Any]:
        row = await self._db.fetch_one(
            "SELECT id, position, label, session_no, status, done_at"
            " FROM section_plan_sections WHERE id = ?",
            (section_id,),
        )
        if row is None:
            raise PlanSectionNotFound(section_id)
        return {
            "id": str(row["id"]),
            "position": int(row["position"]),
            "label": str(row["label"]),
            "sessionNo": row["session_no"],
            "status": str(row["status"]),
            "doneAt": row["done_at"],
        }
