"""F21 个人术语本 —— 用户自建术语的 CRUD 与搜索（SQL 唯一入口）。

- 同词不同含义可并存（term 不唯一，多条同名词目合法）；
- source_ref 可选关联原文（解析为 ItemRef 后才写入，防止任意串）；
- 搜索 = term/definition 的 LIKE 子串（转义，有界）；
- 定义是纯文本，由客户端转义渲染（与笔记同一约定）；
- N083：术语可带 protect 标记 —— 分段翻译的后处理会把译文里大小写
  漂移的受保护术语还原为词表原始词形；任何术语写操作都会推进
  glossary_version（分段翻译缓存身份的一部分，见 ai_translation_segments）。
"""

import uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_TERM = 100
_MAX_DEFINITION = 2000
_COLUMNS = "id, term, definition, source_ref, protect, created_at, updated_at"

_GLOSSARY_VERSION_KEY = "glossary_version"


class GlossaryNotFound(LookupError):
    """术语不存在（404）。"""


class GlossaryInvalid(ValueError):
    """术语/定义非法。"""


def _validate_term(term: str) -> str:
    clean = term.strip() if isinstance(term, str) else ""
    if not clean:
        raise GlossaryInvalid("term must not be empty.")
    if len(clean) > _MAX_TERM:
        raise GlossaryInvalid(f"term too long (max {_MAX_TERM}).")
    return clean


def _validate_definition(definition: str) -> str:
    clean = definition.strip() if isinstance(definition, str) else ""
    if not clean:
        raise GlossaryInvalid("definition must not be empty.")
    if len(clean) > _MAX_DEFINITION:
        raise GlossaryInvalid(f"definition too long (max {_MAX_DEFINITION}).")
    return clean


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "term": str(row["term"]),
        "definition": str(row["definition"]),
        "sourceRef": row["source_ref"],
        "protect": bool(row["protect"]),
        "createdAt": str(row["created_at"] or ""),
        "updatedAt": str(row["updated_at"] or ""),
    }


async def get_glossary_version(db: Database) -> str:
    """现役 glossary 版本号（分段翻译缓存身份的组成部分）。

    0083 迁移把初始值定为空串：与既有缓存行的默认值一致，因此升级
    本身不失效任何缓存；第一次术语写操作把它推进为 '1'，此后每一次
    术语写操作都 +1，旧缓存行自然不再匹配。"""
    await db.migrate()
    row = await db.fetch_one(
        "SELECT value FROM glossary_meta WHERE key = ?", (_GLOSSARY_VERSION_KEY,)
    )
    return str(row["value"]) if row is not None else ""


async def bump_glossary_version(db: Database) -> str:
    """术语写操作后推进版本号（单调 +1；值损坏时回退为时间戳，绝不抛出）。"""
    await db.migrate()
    current = await get_glossary_version(db)
    if current == "":
        nxt = "1"
    else:
        try:
            nxt = str(int(current) + 1)
        except ValueError:
            import time

            nxt = str(int(time.time()))
    await db.execute(
        "INSERT INTO glossary_meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (_GLOSSARY_VERSION_KEY, nxt),
    )
    return nxt


class GlossaryStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        term: str,
        definition: str,
        source_ref: str | None = None,
        protect: bool = False,
    ) -> dict[str, Any]:
        clean_term = _validate_term(term)
        clean_definition = _validate_definition(definition)
        now = utc_now()
        term_id = f"glo-{uuid.uuid4().hex[:16]}"
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO glossary_terms (id, term, definition, source_ref, protect, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (term_id, clean_term, clean_definition, source_ref, int(protect), now, now),
        )
        await bump_glossary_version(self._db)
        return await self.get(term_id)

    async def list_terms(
        self, q: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        await self._db.migrate()
        bounded = max(1, min(limit, 200))
        if q:
            like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            rows = await self._db.fetch_all(
                "SELECT id, term, definition, source_ref, protect, created_at, updated_at FROM glossary_terms WHERE term LIKE ? ESCAPE '\\' OR definition LIKE ? ESCAPE '\\' ORDER BY updated_at DESC LIMIT ?",
                (like, like, bounded),
            )
        else:
            rows = await self._db.fetch_all(
                "SELECT id, term, definition, source_ref, protect, created_at, updated_at FROM glossary_terms ORDER BY updated_at DESC LIMIT ?",
                (bounded,),
            )
        return [_row_to_dict(row) for row in rows]

    async def get(self, term_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, term, definition, source_ref, protect, created_at, updated_at FROM glossary_terms WHERE id = ?",
            (term_id,),
        )
        return _row_to_dict(row) if row is not None else None

    async def update(
        self,
        term_id: str,
        term: str,
        definition: str,
        protect: bool = False,
    ) -> dict[str, Any] | None:
        clean_term = _validate_term(term)
        clean_definition = _validate_definition(definition)
        await self._db.migrate()
        exists = await self._db.fetch_one(
            "SELECT id FROM glossary_terms WHERE id = ?", (term_id,)
        )
        if exists is None:
            return None
        await self._db.execute(
            "UPDATE glossary_terms SET term = ?, definition = ?, protect = ?, updated_at = ? WHERE id = ?",
            (clean_term, clean_definition, int(protect), utc_now(), term_id),
        )
        await bump_glossary_version(self._db)
        return await self.get(term_id)

    async def delete(self, term_id: str) -> bool:
        await self._db.migrate()
        exists = await self._db.fetch_one(
            "SELECT id FROM glossary_terms WHERE id = ?", (term_id,)
        )
        if exists is None:
            return False
        await self._db.execute("DELETE FROM glossary_terms WHERE id = ?", (term_id,))
        await bump_glossary_version(self._db)
        return True
