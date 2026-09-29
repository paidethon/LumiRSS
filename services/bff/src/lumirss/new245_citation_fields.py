"""NEW-245 引文出处补全 —— 引文登记（原始值）+ 用户逐项补充字段。

语义边界（模块存在的理由）：

- citation_records：用户登记的个人引用。author/date_value 可以是
  NULL —— NULL 就是「原始缺失」这个事实本身；原始值一旦登记不改写
  （同一 citation_ref 重复登记 → 409，保原始值不被覆盖）；
- citation_field_supplements：只有用户补充值，每字段（author/date）
  至多一条；补充值永远与原始值分开返回（origin 标注明确）——
  「明确区分原始值和用户补充值」是查询契约，不是展示约定；
- 删除补充 = 撤销补充（恢复缺失态），原始值不动；
- 有效的 author/date = 原始值优先；原始缺失且无补充 → effective
  为 None（缺失就是缺失，不编造）。

per-user 库：登记天然按账户隔离。
"""

import sqlite3
import uuid as _uuid
from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.util import utc_now

_FIELDS = ("author", "date")
_TEXT_MAX = 500
_TITLE_MAX = 500
_REF_MAX = 300


class CitationInvalid(ValueError):
    """引文负载非法（映射 422）。"""


class CitationConflict(Exception):
    """同一 ref 已登记（映射 409，保原始值）。"""


class CitationNotFound(Exception):
    """引文未登记（映射 404）。"""


def _clean(value: Any, *, field: str, max_len: int, required: bool) -> str | None:
    if value is None:
        if required:
            raise CitationInvalid(f"{field} 不能为空。")
        return None
    if not isinstance(value, str):
        raise CitationInvalid(f"{field} 必须是字符串。")
    cleaned = value.strip()
    if not cleaned:
        if required:
            raise CitationInvalid(f"{field} 不能为空。")
        return None
    if len(cleaned) > max_len:
        raise CitationInvalid(f"{field} 超出 {max_len} 字符上限。")
    return cleaned


class CitationFieldStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- 登记 ---------------------------------------------------------------

    async def register(
        self,
        citation_ref: str,
        title: str,
        author: str | None,
        date_value: str | None,
    ) -> dict[str, Any]:
        clean_ref = _clean(citation_ref, field="citationRef", max_len=_REF_MAX, required=True)
        clean_title = _clean(title, field="title", max_len=_TITLE_MAX, required=True)
        clean_author = _clean(author, field="author", max_len=_TEXT_MAX, required=False)
        clean_date = _clean(date_value, field="dateValue", max_len=_TEXT_MAX, required=False)
        now = utc_now()

        def _tx(conn: sqlite3.Connection) -> None:
            existing = conn.execute(
                "SELECT citation_ref FROM citation_records WHERE citation_ref = ?",
                (clean_ref,),
            ).fetchone()
            if existing is not None:
                raise CitationConflict(clean_ref)
            conn.execute(
                "INSERT INTO citation_records (citation_ref, title, author, date_value, registered_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (clean_ref, clean_title, clean_author, clean_date, now),
            )

        await transaction(self._db, _tx)
        return {
            "citationRef": clean_ref,
            "title": clean_title,
            "author": clean_author,
            "dateValue": clean_date,
            "registeredAt": now,
        }

    # -- 查询 ---------------------------------------------------------------

    async def get(self, citation_ref: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT citation_ref, title, author, date_value, registered_at "
            "FROM citation_records WHERE citation_ref = ?",
            (citation_ref,),
        )
        if row is None:
            raise CitationNotFound(citation_ref)
        return await self._view(row)

    async def list_all(self) -> dict[str, Any]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT citation_ref, title, author, date_value, registered_at "
            "FROM citation_records ORDER BY registered_at DESC, citation_ref LIMIT 200",
            (),
        )
        return {"items": [await self._view(row) for row in rows]}

    async def _view(self, row: Any) -> dict[str, Any]:
        supplements = await self._db.fetch_all(
            "SELECT field, value, recorded_at FROM citation_field_supplements "
            "WHERE citation_ref = ?",
            (str(row["citation_ref"]),),
        )
        supp = {str(s["field"]): str(s["value"]) for s in supplements}
        original_author = str(row["author"]) if row["author"] is not None else None
        original_date = str(row["date_value"]) if row["date_value"] is not None else None
        effective_author = original_author if original_author is not None else supp.get("author")
        effective_date = original_date if original_date is not None else supp.get("date")
        return {
            "citationRef": str(row["citation_ref"]),
            "title": str(row["title"]),
            "registeredAt": str(row["registered_at"]),
            "author": {
                "original": original_author,
                "supplement": supp.get("author"),
                "effective": effective_author,
                "origin": "original" if original_author is not None else ("supplement" if supp.get("author") else None),
            },
            "date": {
                "original": original_date,
                "supplement": supp.get("date"),
                "effective": effective_date,
                "origin": "original" if original_date is not None else ("supplement" if supp.get("date") else None),
            },
        }

    # -- 补充字段 ------------------------------------------------------------

    @staticmethod
    def _validate_field(field: str) -> str:
        if field not in _FIELDS:
            raise CitationInvalid("field 必须是 author 或 date。")
        return field

    async def put_supplement(self, citation_ref: str, field: str, value: str) -> dict[str, Any]:
        clean_field = self._validate_field(field)
        clean_value = _clean(value, field="value", max_len=_TEXT_MAX, required=True)
        await self._db.migrate()
        existing = await self._db.fetch_one(
            "SELECT citation_ref FROM citation_records WHERE citation_ref = ?",
            (citation_ref,),
        )
        if existing is None:
            raise CitationNotFound(citation_ref)
        supplement_id = str(_uuid.uuid4())
        now = utc_now()

        def _tx(conn: sqlite3.Connection) -> None:
            row = conn.execute(
                "SELECT id FROM citation_field_supplements WHERE citation_ref = ? AND field = ?",
                (citation_ref, clean_field),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO citation_field_supplements (id, citation_ref, field, value, recorded_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (supplement_id, citation_ref, clean_field, clean_value, now),
                )
            else:
                conn.execute(
                    "UPDATE citation_field_supplements SET value = ? WHERE id = ?",
                    (clean_value, str(row["id"])),
                )

        await transaction(self._db, _tx)
        return {"citationRef": citation_ref, "field": clean_field, "value": clean_value}

    async def delete_supplement(self, citation_ref: str, field: str) -> None:
        clean_field = self._validate_field(field)
        await self._db.migrate()

        def _tx(conn: sqlite3.Connection) -> None:
            conn.execute(
                "DELETE FROM citation_field_supplements WHERE citation_ref = ? AND field = ?",
                (citation_ref, clean_field),
            )

        await transaction(self._db, _tx)
