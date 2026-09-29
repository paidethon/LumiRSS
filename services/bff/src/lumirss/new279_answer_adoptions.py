"""NEW-279 问答结论采纳 —— 回答中的一个结论连同引用移入个人笔记。

- 采纳 = 结论文本 + 引用清单 + 落点笔记（新建或既有）；笔记正文带
  「来源：AI」标记行 + 机器可定位的 HTML 注释锚（ai-adoption:{id}），
  便于后续改写时精确定位这一块；
- 改写（PATCH）带乐观锁：笔记若被用户直接编辑过（updatedAt 漂移）
  → 409 note_diverged（附笔记现状），绝不静默覆盖人工修改；
- 删除采纳只删采纳台账行，笔记内容不动（用户自己决定怎么整理）；
- AI 来源标记永不摘除：改写替换锚块时标记行原样重写。

per-user：笔记与采纳台账都在 per-user 库，A 的采纳对 B 不可见。
"""

import uuid
from typing import Any

from lumirss.lumi_notes import content_hash_of
from lumirss.lumi_notes_lifecycle import NoteLifecycleStore
from lumirss.storage import Database
from lumirss.util import utc_now

MAX_CONCLUSION_CHARS = 6000
MAX_CITATIONS = 20

_ADOPTION_COLUMNS = (
    "id, entry_ref, conclusion, citations, model, note_uuid, "
    "note_updated_at, note_content_hash, created_at, updated_at"
)


class AdoptionInvalid(ValueError):
    """采纳负载非法（映射 422）。"""


class AdoptionNotFound(Exception):
    """采纳记录不存在（映射 404）。"""


class NoteDiverged(Exception):
    """笔记已被直接编辑（updatedAt 漂移）→ 409，附现状不覆盖。"""

    def __init__(self, note_uuid: str, note_updated_at: str, content_md: str) -> None:
        super().__init__("笔记已被直接修改，采纳改写未应用。")
        self.note_uuid = note_uuid
        self.note_updated_at = note_updated_at
        self.content_md = content_md


def _clean_conclusion(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise AdoptionInvalid("conclusion 必填。")
    return raw.strip()[:MAX_CONCLUSION_CHARS]


def _clean_citations(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_CITATIONS:
        raise AdoptionInvalid(f"citations 必须是 ≤{MAX_CITATIONS} 条的数组。")
    cleaned: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise AdoptionInvalid("citations 的元素必须是对象。")
        cleaned.append(
            {
                "index": item.get("index"),
                "entryRef": str(item.get("entryRef") or ""),
            }
        )
    return cleaned


def _block(adoption_id: str, conclusion: str, model: str,
           citations: list[dict[str, Any]]) -> str:
    """笔记中的采纳块：机器锚（HTML 注释）+ 人类可读的 AI 来源标记。"""
    citation_lines = ""
    refs = [c["entryRef"] for c in citations if c["entryRef"]]
    if refs:
        citation_lines = "\n".join(
            f"- [{index + 1}] {ref}" for index, ref in enumerate(refs)
        )
        citation_lines = f"\n引用：\n{citation_lines}"
    model_note = f"（{model}）" if model else ""
    # 块内容必须可复现（改写时按锚精确替换）：不嵌入时间戳——
    # 采纳时间在台账（createdAt）里，笔记里只有稳定的锚 + 来源标记。
    return (
        f"\n\n<!-- ai-adoption:{adoption_id} -->\n"
        f"来源：AI{model_note}\n"
        f"{conclusion}"
        f"{citation_lines}\n"
    )


class AnswerAdoptionStore:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._notes = NoteLifecycleStore(db)

    async def adopt(
        self,
        *,
        conclusion: Any,
        citations: Any = None,
        model: str = "",
        entry_ref: str | None = None,
        note_uuid: str | None = None,
        new_title: str | None = None,
    ) -> dict[str, Any]:
        """采纳到既有笔记或新建笔记（标记行随块写入）。"""
        clean_conclusion = _clean_conclusion(conclusion)
        clean_citations = _clean_citations(citations)
        adoption_id = uuid.uuid4().hex[:20]
        block = _block(adoption_id, clean_conclusion, model, clean_citations)
        if note_uuid:
            note = await self._get_note(note_uuid)
            new_content = note["content_md"] + block
            updated = await self._notes.update_note(
                note_uuid,
                title=None,
                content_md=new_content,
                base_updated_at=note["updated_at"],  # 采纳前刚读过 → 精确锚定
            )
            note_updated_at = updated["updatedAt"]
        else:
            title = (new_title or "").strip()[:200] or "AI 问答结论"
            created = await self._notes.create_note(
                title=title, content_md=block.strip() + "\n", workspace_id=None,
            )
            note_uuid = created["uuid"]
            note_updated_at = created["updatedAt"]
        final_note = await self._get_note(note_uuid)
        # 改写冲突判定基准：写入采纳块后整篇笔记的 sha256（比 updatedAt
        # 秒级时间戳更严：同一秒内的人工编辑也逃不掉）。
        note_content_hash = content_hash_of(final_note["content_md"])
        await self._db.migrate()
        now = utc_now()
        await self._db.execute(
            "INSERT INTO ai_answer_adoptions (id, entry_ref, conclusion, citations, "
            "model, note_uuid, note_updated_at, note_content_hash, created_at, "
            "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                adoption_id,
                entry_ref,
                clean_conclusion,
                _dump_citations(clean_citations),
                model,
                note_uuid,
                note_updated_at,
                note_content_hash,
                now,
                now,
            ),
        )
        return await self.get_adoption(adoption_id)

    async def revise(
        self, adoption_id: str, *, conclusion: Any
    ) -> dict[str, Any]:
        """改写结论（可改写；AI 来源标记保留）。

        笔记自上次采纳写入后被人工编辑（整篇内容 sha256 与台账漂移）
        → NoteDiverged，附笔记现状；用户解决后可重新 PATCH。哈希比
        updatedAt 更严：同一秒内的人工编辑（秒级时间戳看不出漂移）
        也会被拦下，绝不静默覆盖。"""
        adoption = await self.get_adoption(adoption_id)
        clean_conclusion = _clean_conclusion(conclusion)
        note_uuid = adoption["noteUuid"]
        note = await self._get_note(note_uuid)
        if content_hash_of(note["content_md"]) != adoption["noteContentHash"]:
            raise NoteDiverged(note_uuid, note["updated_at"], note["content_md"])
        old_block = _block(
            adoption_id,
            adoption["conclusion"],
            adoption["model"],
            _load_citations(adoption["citations"]),
        )
        new_block = _block(
            adoption_id,
            clean_conclusion,
            adoption["model"],
            _load_citations(adoption["citations"]),
        )
        content = note["content_md"]
        if old_block in content:
            new_content = content.replace(old_block, new_block)
        elif old_block.strip() in content:
            # 新建笔记落点存的是 strip 后的块（无块首空行）→ 紧凑形式
            # 等价替换，标记行与机器锚原样保留。
            new_content = content.replace(old_block.strip(), new_block.strip())
        else:
            # 用户删过这一块：按「追加 + 新锚」重建（不恢复旧文本）。
            new_content = content + new_block
        await self._notes.update_note(
            note_uuid,
            title=None,
            content_md=new_content,
            base_updated_at=note["updated_at"],
        )
        refreshed = await self._get_note(note_uuid)
        await self._db.execute(
            "UPDATE ai_answer_adoptions SET conclusion = ?, note_updated_at = ?, "
            "note_content_hash = ?, updated_at = ? WHERE id = ?",
            (
                clean_conclusion,
                refreshed["updated_at"],
                content_hash_of(refreshed["content_md"]),
                utc_now(),
                adoption_id,
            ),
        )
        return await self.get_adoption(adoption_id)

    async def delete_adoption(self, adoption_id: str) -> bool:
        """删除采纳记录（笔记内容不动——用户自己整理）。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id FROM ai_answer_adoptions WHERE id = ?", (adoption_id,)
        )
        if row is None:
            return False
        await self._db.execute(
            "DELETE FROM ai_answer_adoptions WHERE id = ?", (adoption_id,)
        )
        return True

    async def list_adoptions(self, limit: int = 20) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            f"SELECT {_ADOPTION_COLUMNS} FROM ai_answer_adoptions "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (max(1, min(limit, 100)),),
        )
        return [_row(row) for row in rows]

    async def get_adoption(self, adoption_id: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            f"SELECT {_ADOPTION_COLUMNS} FROM ai_answer_adoptions WHERE id = ?",
            (adoption_id,),
        )
        if row is None:
            raise AdoptionNotFound(adoption_id)
        return _row(row)

    async def _get_note(self, note_uuid: str) -> dict[str, Any]:
        row = await self._db.fetch_one(
            "SELECT uuid, content_md, updated_at, deleted_at FROM lumi_notes "
            "WHERE uuid = ?",
            (note_uuid,),
        )
        if row is None or row["deleted_at"] is not None:
            raise AdoptionInvalid("落点笔记不存在（或已删除）。")
        return {
            "uuid": str(row["uuid"]),
            "content_md": str(row["content_md"]),
            "updated_at": str(row["updated_at"]),
        }


def _dump_citations(citations: list[dict[str, Any]]) -> str:
    import json

    return json.dumps(citations, ensure_ascii=False)


def _load_citations(raw: Any) -> list[dict[str, Any]]:
    import json

    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(str(raw or "[]"))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _row(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "entryRef": row["entry_ref"],
        "conclusion": str(row["conclusion"]),
        "citations": _load_citations(row["citations"]),
        "model": str(row["model"] or ""),
        "noteUuid": str(row["note_uuid"]),
        "noteUpdatedAt": str(row["note_updated_at"]),
        "noteContentHash": str(row["note_content_hash"] or ""),
        "createdAt": str(row["created_at"]),
        "updatedAt": str(row["updated_at"]),
    }
