"""NEW-213 标签互斥组 —— 用户定义「这组标签至多选一个」。

- 组按 tag_id 引用成员（改名自动跟随）；成员必须是已存在的标签；
- 冲突视图：某条内容同时绑定了组内 ≥2 个标签 → 列出（服务端真实
  查询，上限 200 条，诚实截断）；
- 批量解决：逐条指定保留值（keep），其余组内标签从该内容上拆下
  （DELETE item_tags，Lumi 自有域；FreshRSS 零接触）。keep 必须是
  该组现有成员；未冲突的 ref 会被拒绝（绝不盲拆）。
"""

import sqlite3
from typing import Any

from lumirss.db_tx import transaction
from lumirss.itemref import parse_item_ref
from lumirss.storage import Database
from lumirss.tags import normalize_tag_name
from lumirss.util import utc_now

_MAX_GROUPS = 50
_MAX_MEMBERS = 30
_MIN_MEMBERS = 2
_MAX_NAME = 64
_MAX_CONFLICT_ITEMS = 200
_MAX_RESOLVE_BATCH = 200


class TagGroupInvalid(ValueError):
    """组定义/解决载荷非法（名字、成员数、未知标签/ref），映射 422。"""


class TagGroupNotFound(Exception):
    """没有这个互斥组，映射 404。"""


class TagGroupConflictRequest(Exception):
    """解决载荷与冲突现状不符（keep 不是成员/ref 无冲突），映射 409。"""


class TagGroupStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, name: str, member_names: list[str]) -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name or len(clean_name) > _MAX_NAME:
            raise TagGroupInvalid(f"组名必须是 1-{_MAX_NAME} 个字符。")
        cleaned: list[str] = []
        for raw in member_names:
            member = normalize_tag_name(raw)
            if member not in cleaned:
                cleaned.append(member)
        if not _MIN_MEMBERS <= len(cleaned) <= _MAX_MEMBERS:
            raise TagGroupInvalid(f"成员数量必须是 {_MIN_MEMBERS}-{_MAX_MEMBERS} 个标签。")
        await self._db.migrate()
        count = await self._db.fetch_one("SELECT COUNT(*) AS n FROM new213_tag_groups")
        if count is not None and int(count["n"]) >= _MAX_GROUPS:
            raise TagGroupInvalid(f"互斥组数量已达上限（{_MAX_GROUPS}）。")
        placeholders = ",".join("?" * len(cleaned))
        rows = await self._db.fetch_all(
            f"SELECT id, name FROM tags WHERE name IN ({placeholders}) COLLATE NOCASE",
            (*cleaned,),
        )
        by_name = {str(r["name"]).lower(): int(r["id"]) for r in rows}
        missing = [m for m in cleaned if m.lower() not in by_name]
        if missing:
            raise TagGroupInvalid(f"以下标签不存在，请先创建：{'、'.join(missing)}。")

        def _create(conn: sqlite3.Connection) -> dict[str, Any]:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "INSERT INTO new213_tag_groups (name, created_at) VALUES (?, ?)",
                (clean_name, utc_now()),
            )
            group_id = int(cur.lastrowid)
            for member in cleaned:
                conn.execute(
                    "INSERT INTO new213_tag_group_members (group_id, tag_id) VALUES (?, ?)",
                    (group_id, by_name[member.lower()]),
                )
            return {"id": group_id, "name": clean_name, "members": cleaned}

        return await transaction(self._db, _create)

    async def list_groups(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        groups = await self._db.fetch_all(
            "SELECT id, name, created_at FROM new213_tag_groups ORDER BY id ASC"
        )
        members = await self._db.fetch_all(
            "SELECT m.group_id, t.id AS tag_id, t.name FROM new213_tag_group_members m JOIN tags t ON t.id = m.tag_id ORDER BY t.name ASC"
        )
        by_group: dict[int, list[dict[str, Any]]] = {}
        for row in members:
            by_group.setdefault(int(row["group_id"]), []).append(
                {"tagId": int(row["tag_id"]), "name": str(row["name"])}
            )
        return [
            {
                "id": int(g["id"]),
                "name": str(g["name"]),
                "createdAt": str(g["created_at"]),
                "members": by_group.get(int(g["id"]), []),
            }
            for g in groups
        ]

    async def delete(self, group_id: int) -> bool:
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT id FROM new213_tag_groups WHERE id = ?", (group_id,))
        if row is None:
            return False
        await self._db.execute("DELETE FROM new213_tag_groups WHERE id = ?", (group_id,))
        return True

    async def conflicts(self, group_id: int) -> dict[str, Any]:
        """组内 ≥2 标签同时绑定的内容（服务端真实查询，上限 200）。"""
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT id FROM new213_tag_groups WHERE id = ?", (group_id,))
        if row is None:
            raise TagGroupNotFound(str(group_id))

        def _conflicts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
            member_ids = self._member_ids_sync(conn, group_id)
            if len(member_ids) < 2:
                return []
            placeholders = ",".join("?" * len(member_ids))
            rows = conn.execute(
                "SELECT it.item_ref, t.id AS tag_id, t.name FROM item_tags it"
                " JOIN tags t ON t.id = it.tag_id"
                f" WHERE it.tag_id IN ({placeholders}) AND it.status = 'active'"
                " ORDER BY it.item_ref ASC",
                (*member_ids,),
            ).fetchall()
            by_ref: dict[str, list[dict[str, Any]]] = {}
            for r in rows:
                by_ref.setdefault(str(r["item_ref"]), []).append(
                    {"tagId": int(r["tag_id"]), "name": str(r["name"])}
                )
            conflicts = [
                {"ref": ref, "tags": tags}
                for ref, tags in sorted(by_ref.items())
                if len(tags) >= 2
            ]
            return conflicts[:_MAX_CONFLICT_ITEMS]

        items = await transaction(self._db, _conflicts)
        return {
            "groupId": group_id,
            "items": items,
            "truncated": len(items) >= _MAX_CONFLICT_ITEMS,
        }

    def _member_ids_sync(self, conn: sqlite3.Connection, group_id: int) -> list[int]:
        rows = conn.execute(
            "SELECT tag_id FROM new213_tag_group_members WHERE group_id = ?",
            (group_id,),
        ).fetchall()
        return [int(r["tag_id"]) for r in rows]

    async def resolve(
        self, group_id: int, resolutions: list[dict[str, str]]
    ) -> dict[str, Any]:
        """批量解决冲突：每条 {ref, keep}；keep 必须绑定在该 ref 上且是
        组成员；其余组内绑定被拆下。单条不满足 → 整批拒绝（409）。"""
        if not resolutions or len(resolutions) > _MAX_RESOLVE_BATCH:
            raise TagGroupInvalid(f"解决条数必须是 1-{_MAX_RESOLVE_BATCH}。")
        cleaned: list[tuple[str, str]] = []
        seen: set[str] = set()
        for item in resolutions:
            if not isinstance(item, dict):
                raise TagGroupInvalid("每条解决项必须是对象。")
            ref = parse_item_ref(str(item.get("ref") or "")).format()
            keep = normalize_tag_name(str(item.get("keep") or ""))
            if ref in seen:
                raise TagGroupInvalid("同一内容不能出现两条解决项。")
            seen.add(ref)
            cleaned.append((ref, keep))
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT id FROM new213_tag_groups WHERE id = ?", (group_id,))
        if row is None:
            raise TagGroupNotFound(str(group_id))

        def _resolve(conn: sqlite3.Connection) -> dict[str, Any]:
            conn.execute("BEGIN IMMEDIATE")
            member_ids = self._member_ids_sync(conn, group_id)
            placeholders = ",".join("?" * len(member_ids))
            name_rows = conn.execute(
                f"SELECT id, name FROM tags WHERE id IN ({placeholders})",
                (*member_ids,),
            ).fetchall()
            keep_ids = {
                str(r["name"]).lower(): int(r["id"]) for r in name_rows
            }
            bound_rows = conn.execute(
                "SELECT it.item_ref, it.tag_id FROM item_tags it"
                f" WHERE it.item_ref IN ({','.join('?' * len(cleaned))})"
                f" AND it.tag_id IN ({placeholders}) AND it.status = 'active'",
                (*[ref for ref, _ in cleaned], *member_ids),
            ).fetchall()
            bound: dict[str, set[int]] = {}
            for r in bound_rows:
                bound.setdefault(str(r["item_ref"]), set()).add(int(r["tag_id"]))
            # 整批预检：任一条不满足 → 抛出回滚。
            for ref, keep in cleaned:
                keep_id = keep_ids.get(keep.lower())
                if keep_id is None:
                    raise TagGroupConflictRequest(f"「{keep}」不是该互斥组的成员。")
                if keep_id not in bound.get(ref, set()):
                    raise TagGroupConflictRequest(
                        f"内容 {ref} 没有组内冲突（或未绑定「{keep}」），拒绝盲拆。"
                    )
            resolved: list[dict[str, Any]] = []
            for ref, keep in cleaned:
                keep_id = keep_ids[keep.lower()]
                removed: list[str] = []
                for member_id in member_ids:
                    if member_id == keep_id or member_id not in bound.get(ref, set()):
                        continue
                    name_row = conn.execute(
                        "SELECT name FROM tags WHERE id = ?", (member_id,)
                    ).fetchone()
                    conn.execute(
                        "DELETE FROM item_tags WHERE item_ref = ? AND tag_id = ?",
                        (ref, member_id),
                    )
                    removed.append(str(name_row["name"]) if name_row is not None else str(member_id))
                resolved.append({"ref": ref, "kept": keep, "removed": removed})
            return {"groupId": group_id, "resolved": resolved}

        try:
            return await transaction(self._db, _resolve)
        except sqlite3.Error as exc:
            raise TagGroupInvalid("解决失败。") from exc
