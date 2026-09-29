"""NEW-335 共读分歧记录 —— 把不同结论及各自引用**并列**保存；空间成员
可补充证据；不强制生成统一结论。

设计要点：

- 每位成员对同一分歧至多持有一个立场（upsert：改写自己的结论/引用），
  立场行按作者并列呈现——没有「合并结论」字段，也永远不自动合并；
- 引用（citations）是作者显式填写的 [{ref?, note?}] 快照；
- 证据（evidence）由任何成员补充，可挂在某一立场上或分歧整体；
- 闭合（closed）只是可选的停止写入，不是「达成一致」。
"""

import json
import uuid as _uuid
from typing import Any

from lumirss.space_core import MAX_NAME, SpaceForbidden, SpaceInvalid, SpaceStore
from lumirss.storage import Database
from lumirss.util import utc_now

MAX_CONCLUSION = 4000
MAX_CITATIONS = 20
MAX_CITATION_NOTE = 500
MAX_EVIDENCE_NOTE = 1000
MAX_POSITIONS = 100


class DisagreementNotFound(Exception):
    """分歧记录不存在（或不属于该空间）——404。"""


def _clean(value: Any, field: str, limit: int, *, required: bool = True) -> str:
    if value is None:
        if required:
            raise SpaceInvalid(f"{field} 不能为空。")
        return ""
    if not isinstance(value, str):
        raise SpaceInvalid(f"{field} 必须是字符串。")
    clean = value.strip()
    if required and not clean:
        raise SpaceInvalid(f"{field} 不能为空。")
    if len(clean) > limit:
        raise SpaceInvalid(f"{field} 最长 {limit} 字符。")
    return clean


def parse_citations(value: Any) -> list[dict[str, str]]:
    """引用列表：[{ref?, note?}]，全部显式填写；序列化为 JSON 存储。"""
    if value is None:
        return []
    if not isinstance(value, list):
        raise SpaceInvalid("citations 必须是数组。")
    citations: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise SpaceInvalid("citations 项必须是对象。")
        ref = _clean(item.get("ref"), "citations.ref", 200, required=False)
        note = _clean(item.get("note"), "citations.note", MAX_CITATION_NOTE, required=False)
        if not ref and not note:
            raise SpaceInvalid("引用项至少要有 ref 或 note。")
        citations.append({"ref": ref, "note": note})
        if len(citations) > MAX_CITATIONS:
            raise SpaceInvalid(f"引用最多 {MAX_CITATIONS} 条。")
    return citations


class DisagreementStore:
    def __init__(self, control_db: Database, spaces: SpaceStore) -> None:
        self._db = control_db
        self._spaces = spaces

    async def _row(self, space_id: str, disagreement_id: str) -> dict[str, Any]:
        row = await self._db.fetch_one(
            "SELECT * FROM space_disagreements WHERE id = ? AND space_id = ?",
            (disagreement_id, space_id),
        )
        if row is None:
            raise DisagreementNotFound(disagreement_id)
        return dict(row)

    async def _positions(self, disagreement_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM space_disagreement_positions WHERE disagreement_id = ? ORDER BY created_at ASC, rowid ASC",
            (disagreement_id,),
        )
        return [
            {
                "id": str(row["id"]),
                "disagreementId": str(row["disagreement_id"]),
                "authorUserId": str(row["author_user_id"]),
                "authorUsername": str(row["author_username"]),
                "conclusion": str(row["conclusion"]),
                "citations": json.loads(str(row["citations_json"] or "[]")),
                "createdAt": str(row["created_at"]),
                "updatedAt": str(row["updated_at"]),
            }
            for row in rows
        ]

    async def _evidence(self, disagreement_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM space_disagreement_evidence WHERE disagreement_id = ? ORDER BY created_at ASC, rowid ASC",
            (disagreement_id,),
        )
        return [
            {
                "id": str(row["id"]),
                "disagreementId": str(row["disagreement_id"]),
                "positionId": row["position_id"],
                "addedBy": str(row["added_by"]),
                "addedByUsername": str(row["added_by_username"]),
                "note": str(row["note"]),
                "ref": row["ref"],
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]

    async def _view(
        self,
        row: dict[str, Any],
        *,
        with_positions: bool = True,
    ) -> dict[str, Any]:
        view = {
            "id": str(row["id"]),
            "spaceId": str(row["space_id"]),
            "entryRef": row["entry_ref"],
            "title": str(row["title"]),
            "status": str(row["status"]),
            "createdBy": str(row["created_by"]),
            "createdByUsername": str(row["created_by_username"]),
            "closedAt": row["closed_at"],
            "createdAt": str(row["created_at"]),
        }
        if with_positions:
            view["positions"] = await self._positions(str(row["id"]))
            view["evidence"] = await self._evidence(str(row["id"]))
        return view

    # -- 动作 -----------------------------------------------------------------

    async def create(
        self,
        space_id: str,
        *,
        actor_user_id: str,
        actor_username: str,
        title: Any,
        entry_ref: Any = None,
    ) -> dict[str, Any]:
        await self._spaces.require_member(space_id, actor_user_id, write=True)
        clean_title = _clean(title, "title", MAX_NAME)
        ref = _clean(entry_ref, "entryRef", 200, required=False) or None
        now = utc_now()
        disagreement_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO space_disagreements (id, space_id, entry_ref, title, status, created_by, created_by_username, closed_at, created_at) "
            "VALUES (?, ?, ?, ?, 'open', ?, ?, NULL, ?)",
            (disagreement_id, space_id, ref, clean_title, actor_user_id, actor_username, now),
        )
        return await self._view(await self._row(space_id, disagreement_id))

    async def get(
        self, space_id: str, disagreement_id: str, *, actor_user_id: str
    ) -> dict[str, Any]:
        await self._spaces.require_member(space_id, actor_user_id)
        return await self._view(await self._row(space_id, disagreement_id))

    async def list_for_space(
        self, space_id: str, *, actor_user_id: str
    ) -> list[dict[str, Any]]:
        await self._spaces.require_member(space_id, actor_user_id)
        rows = await self._db.fetch_all(
            "SELECT * FROM space_disagreements WHERE space_id = ? ORDER BY created_at DESC, rowid DESC",
            (space_id,),
        )
        return [await self._view(dict(row), with_positions=False) for row in rows]

    async def upsert_position(
        self,
        space_id: str,
        disagreement_id: str,
        *,
        actor_user_id: str,
        actor_username: str,
        conclusion: Any,
        citations: Any = None,
    ) -> dict[str, Any]:
        """并列保存自己的结论（每人一条，可改写自己的——不动他人）。"""
        await self._spaces.require_member(space_id, actor_user_id, write=True)
        row = await self._row(space_id, disagreement_id)
        if str(row["status"]) != "open":
            raise SpaceInvalid("分歧已闭合，不能再补充立场。")
        clean_conclusion = _clean(conclusion, "conclusion", MAX_CONCLUSION)
        clean_citations = parse_citations(citations)
        now = utc_now()
        existing = await self._db.fetch_one(
            "SELECT id FROM space_disagreement_positions WHERE disagreement_id = ? AND author_user_id = ?",
            (disagreement_id, actor_user_id),
        )
        if existing is not None:
            await self._db.execute(
                "UPDATE space_disagreement_positions SET conclusion = ?, citations_json = ?, updated_at = ? WHERE id = ?",
                (clean_conclusion, json.dumps(clean_citations, ensure_ascii=False), now, str(existing["id"])),
            )
        else:
            count = await self._db.fetch_one(
                "SELECT COUNT(*) AS n FROM space_disagreement_positions WHERE disagreement_id = ?",
                (disagreement_id,),
            )
            if count is not None and int(count["n"]) >= MAX_POSITIONS:
                raise SpaceInvalid(f"立场最多 {MAX_POSITIONS} 条。")
            await self._db.execute(
                "INSERT INTO space_disagreement_positions (id, disagreement_id, space_id, author_user_id, author_username, conclusion, citations_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(_uuid.uuid4()),
                    disagreement_id,
                    space_id,
                    actor_user_id,
                    actor_username,
                    clean_conclusion,
                    json.dumps(clean_citations, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return await self._view(await self._row(space_id, disagreement_id))

    async def add_evidence(
        self,
        space_id: str,
        disagreement_id: str,
        *,
        actor_user_id: str,
        actor_username: str,
        note: Any,
        ref: Any = None,
        position_id: Any = None,
    ) -> dict[str, Any]:
        await self._spaces.require_member(space_id, actor_user_id, write=True)
        await self._row(space_id, disagreement_id)
        clean_note = _clean(note, "note", MAX_EVIDENCE_NOTE)
        clean_ref = _clean(ref, "ref", 200, required=False) or None
        clean_position = _clean(position_id, "positionId", 64, required=False) or None
        if clean_position is not None:
            found = await self._db.fetch_one(
                "SELECT id FROM space_disagreement_positions WHERE id = ? AND disagreement_id = ?",
                (clean_position, disagreement_id),
            )
            if found is None:
                raise SpaceInvalid("要补充的立场不存在。")
        evidence_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO space_disagreement_evidence (id, disagreement_id, position_id, added_by, added_by_username, note, ref, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (evidence_id, disagreement_id, clean_position, actor_user_id, actor_username, clean_note, clean_ref, utc_now()),
        )
        return await self._view(await self._row(space_id, disagreement_id))

    async def close(
        self, space_id: str, disagreement_id: str, *, actor_user_id: str, closed: Any
    ) -> dict[str, Any]:
        """可选闭合（发起者或管理者）——不是强制统一结论，只是停笔。"""
        membership = await self._spaces.require_member(space_id, actor_user_id, write=True)
        if not isinstance(closed, bool):
            raise SpaceInvalid("closed 必须是布尔值。")
        row = await self._row(space_id, disagreement_id)
        is_manager = str(membership["role"]) == "manager"
        if str(row["created_by"]) != actor_user_id and not is_manager:
            raise SpaceForbidden(space_id)
        now = utc_now()
        await self._db.execute(
            "UPDATE space_disagreements SET status = ?, closed_at = ? WHERE id = ?",
            ("closed" if closed else "open", now if closed else None, disagreement_id),
        )
        return await self._view(await self._row(space_id, disagreement_id))
