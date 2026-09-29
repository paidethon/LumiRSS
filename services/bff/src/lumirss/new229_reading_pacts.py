"""NEW-229 阅读约定卡 —— 与一位共读成员约定同一资料和截止时间。

**诚实边界（本部署的现实）**：Lumi 是邀请制多账户，业务数据按用户
分库（0067 / user_scope），产品面**没有跨账户共享表面**（admin 只管
生命周期，没有读成员内容的路由；横向隔离是安全不变量）。因此：

- 约定在**双方各自的库里各有一行**，以 ``pact_key``（创建方生成的
  共持口令）为同一约定的锚：创建方把 key 交给对方（应用外交接，
  与邀请码同型），对方 join 后在自己的库里建对称行；
- 「双方独立确认」= 各自 confirm 自己的那一行（my_status），绝无
  一方能写另一方的库；
- **对方的确认状态在本部署不可见**：读取面恒返回
  ``counterpartVisibility: "unavailable-cross-user"``，绝不伪造
  「对方已完成」；这是被部署形态诚实挡住的能力，不是隐藏。
- 共读成员只看约定本身（资料/截止/自己的确认），看不到彼此的私人
  阅读轨迹（阅读状态、队列、便签全在各自库内，天然隔离）。
"""

import uuid
from typing import Any

from lumirss.itemref import InvalidItemRef, parse_item_ref
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_USERNAME = 60
_MAX_TITLE = 200
_CROSS_USER_VISIBILITY = "unavailable-cross-user"


class PactInvalid(Exception):
    """约定载荷非法——422 invalid_reading_pact。"""


class PactNotFound(Exception):
    """约定不存在（或不属于当前用户）——404 reading_pact_not_found。"""


def validate_ref(value: str) -> str:
    try:
        parse_item_ref(value)
    except InvalidItemRef as exc:
        raise PactInvalid(f"itemRef 不合法：{exc}") from exc
    return value


def validate_username(username: str) -> str:
    if not isinstance(username, str):
        raise PactInvalid("counterpartUsername 必须是字符串。")
    clean = username.strip()
    if not clean:
        raise PactInvalid("counterpartUsername 不能为空。")
    if len(clean) > _MAX_USERNAME:
        raise PactInvalid(f"counterpartUsername 最长 {_MAX_USERNAME} 字符。")
    return clean


def validate_title(title: str | None) -> str | None:
    if title is None:
        return None
    if not isinstance(title, str):
        raise PactInvalid("materialTitle 必须是字符串或 null。")
    clean = title.strip()
    if not clean:
        return None
    if len(clean) > _MAX_TITLE:
        raise PactInvalid(f"materialTitle 最长 {_MAX_TITLE} 字符。")
    return clean


def validate_deadline(deadline: str) -> str:
    """截止时间（ISO 日期或时间戳；存原样字符串，呈现侧解析）。"""
    if not isinstance(deadline, str) or not deadline.strip():
        raise PactInvalid("deadline 必须是 ISO 日期或时间戳。")
    from datetime import datetime

    clean = deadline.strip()
    normalized = clean.replace("Z", "+00:00")
    try:
        datetime.fromisoformat(normalized)
    except ValueError:
        try:
            datetime.strptime(clean, "%Y-%m-%d")
        except ValueError as exc:
            raise PactInvalid(f"deadline 不是合法日期：{clean}") from exc
    return clean


class ReadingPactStore:
    """Persistence for reading_pacts (per-user rows, shared pact_key)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def _view(row: Any) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "pactKey": str(row["pact_key"]),
            "itemRef": str(row["item_ref"]),
            "materialTitle": row["material_title"],
            "deadline": str(row["deadline"]),
            "counterpartUsername": str(row["counterpart_username"]),
            "myStatus": str(row["my_status"]),
            "confirmedAt": row["confirmed_at"],
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
            "counterpartVisibility": _CROSS_USER_VISIBILITY,
        }

    _SELECT = (
        "SELECT p.id, p.pact_key, p.item_ref, p.material_title, p.deadline,"
        " p.counterpart_username, p.my_status, p.confirmed_at, p.created_at,"
        " p.updated_at, se.title AS projection_title"
        " FROM reading_pacts p"
        " LEFT JOIN search_entries se ON se.entry_ref = substr(p.item_ref, 5)"
    )

    async def _row(self, pact_id: str) -> dict[str, Any]:
        row = await self._db.fetch_one(self._SELECT + " WHERE p.id = ?", (pact_id,))
        if row is None:
            raise PactNotFound(pact_id)
        view = self._view(row)
        if row["projection_title"] and not view["materialTitle"]:
            view["materialTitle"] = row["projection_title"]
        return view

    async def create(
        self,
        item_ref: str,
        deadline: str,
        counterpart_username: str,
        material_title: str | None = None,
    ) -> dict[str, Any]:
        """发起约定（201）：生成共持 pact_key（交给对方 join 用）。"""
        await self._db.migrate()
        validate_ref(item_ref)
        clean_deadline = validate_deadline(deadline)
        clean_username = validate_username(counterpart_username)
        clean_title = validate_title(material_title)
        pact_id = f"pact-{uuid.uuid4().hex}"
        pact_key = uuid.uuid4().hex
        now = utc_now()
        await self._db.execute(
            "INSERT INTO reading_pacts (id, pact_key, item_ref, material_title,"
            " deadline, counterpart_username, my_status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
            (pact_id, pact_key, item_ref, clean_title, clean_deadline,
             clean_username, now, now),
        )
        return await self._row(pact_id)

    async def join(
        self,
        pact_key: str,
        item_ref: str,
        deadline: str,
        counterpart_username: str,
        material_title: str | None = None,
    ) -> dict[str, Any]:
        """以共持 pact_key 在**自己库**里建对称行（201）。

        同一 key 重复 join → 幂等返回已有行（绝不建第二行）。新行复用
        传入的 pact_key（同一约定的锚）。服务端无法（也不应）跨库验证
        key 归属——key 的可信交接在应用外完成，与邀请码同型。"""
        await self._db.migrate()
        if not isinstance(pact_key, str) or len(pact_key) < 16 or len(pact_key) > 64:
            raise PactInvalid("pactKey 格式不合法。")
        clean_key = pact_key.strip()
        if not clean_key:
            raise PactInvalid("pactKey 不能为空。")
        existing = await self._db.fetch_one(
            "SELECT id FROM reading_pacts WHERE pact_key = ?", (clean_key,)
        )
        if existing is not None:
            return await self._row(str(existing["id"]))
        validate_ref(item_ref)
        clean_deadline = validate_deadline(deadline)
        clean_username = validate_username(counterpart_username)
        clean_title = validate_title(material_title)
        pact_id = f"pact-{uuid.uuid4().hex}"
        now = utc_now()
        await self._db.execute(
            "INSERT INTO reading_pacts (id, pact_key, item_ref, material_title,"
            " deadline, counterpart_username, my_status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
            (pact_id, clean_key, item_ref, clean_title, clean_deadline,
             clean_username, now, now),
        )
        return await self._row(pact_id)

    async def confirm(self, pact_id: str, confirmed: bool) -> dict[str, Any]:
        """独立确认完成（set 语义；只能确认自己库里的行）。"""
        await self._db.migrate()
        row = await self._row(pact_id)
        if row["myStatus"] == "archived":
            raise PactInvalid("约定已归档：先取消归档再确认。")
        status = "confirmed" if confirmed else "pending"
        await self._db.execute(
            "UPDATE reading_pacts SET my_status = ?, confirmed_at = ?,"
            " updated_at = ? WHERE id = ?",
            (status, utc_now() if confirmed else None, utc_now(), pact_id),
        )
        return await self._row(pact_id)

    async def archive(self, pact_id: str, archived: bool) -> dict[str, Any]:
        """归档（约定生命周期结束；set 语义；归档保留 confirmed_at
        历史，取消归档回到 pending 并清确认时间）。"""
        await self._db.migrate()
        await self._row(pact_id)
        if archived:
            await self._db.execute(
                "UPDATE reading_pacts SET my_status = 'archived',"
                " updated_at = ? WHERE id = ?",
                (utc_now(), pact_id),
            )
        else:
            await self._db.execute(
                "UPDATE reading_pacts SET my_status = 'pending',"
                " confirmed_at = NULL, updated_at = ? WHERE id = ?",
                (utc_now(), pact_id),
            )
        return await self._row(pact_id)

    async def list_pacts(self, include_archived: bool = False) -> dict[str, Any]:
        await self._db.migrate()
        where = ""
        if not include_archived:
            where = " WHERE p.my_status != 'archived'"
        rows = await self._db.fetch_all(
            self._SELECT + where + " ORDER BY p.deadline ASC, p.rowid ASC"
        )
        items = []
        for row in rows:
            view = self._view(row)
            if row["projection_title"] and not view["materialTitle"]:
                view["materialTitle"] = row["projection_title"]
            items.append(view)
        return {
            "items": items,
            "counterpartVisibility": _CROSS_USER_VISIBILITY,
            "note": (
                "约定双方各持一行（同一 pactKey 锚定）；确认是独立动作，"
                "对方的确认状态在本部署不可见（无跨账户共享表面）。"
            ),
        }

    async def delete(self, pact_id: str) -> None:
        """删除自己库里的约定行（显式动作；不影响对方的行）。"""
        await self._db.migrate()
        await self._row(pact_id)  # 404 when missing
        await self._db.execute("DELETE FROM reading_pacts WHERE id = ?", (pact_id,))
