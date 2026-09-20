"""F023 跨来源作者聚合 —— author_aliases 的 SQL 唯一入口 + 聚合读路径。

边界（诚实口径）：

- ``search_entries.author`` 的精确相同值天然同组（同名字符串即同 key）；
- 别名（alias → canonical）只由用户显式建立，用于把「不同写法归一人」
  （如「张三」与「Zhang San」）；绝不按大小写/CJK 规范自动归并；
- 空 author（''）排除在聚合之外；
- 聚合在 SQL 侧折叠 alias → canonical，计数真实（GROUP BY 全表）。
"""

from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_AUTHOR_CHARS = 200


class AuthorAliasInvalid(ValueError):
    """别名非法（alias == canonical / 超长 / 空串）。"""


class AuthorAliasNotFound(Exception):
    """别名不存在（404）。"""


def _clean_author(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorAliasInvalid(f"{field} 不能为空。")
    clean = value.strip()
    if len(clean) > _MAX_AUTHOR_CHARS:
        raise AuthorAliasInvalid(f"{field} 过长（最多 {_MAX_AUTHOR_CHARS} 字）。")
    return clean


# 规范名折叠：author 命中别名表时换成 canonical；其余保持原值。
# （输出列名 canonical 不能叫 author——GROUP BY 会先解析回源列。）
_CANONICAL_SQL = (
    "CASE WHEN s.author IN (SELECT alias FROM author_aliases) "
    "THEN (SELECT canonical FROM author_aliases WHERE alias = s.author) "
    "ELSE s.author END"
)


def _row_to_author(row: Any) -> dict[str, Any]:
    return {"author": str(row["canonical"]), "count": int(row["n"])}


class AuthorAggregateStore:
    """作者聚合读路径 + 别名 CRUD（内联 SQL + 绑定参数）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    # -- 聚合 ---------------------------------------------------------

    async def list_authors(
        self, *, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """按 canonical author 聚合条目数（排除空 author；计数降序）。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            f"SELECT {_CANONICAL_SQL} AS canonical, COUNT(*) AS n FROM search_entries s "
            "WHERE s.author != '' GROUP BY canonical ORDER BY n DESC, canonical ASC "
            "LIMIT ? OFFSET ?",
            (max(1, min(limit, 200)), max(0, offset)),
        )
        return [_row_to_author(row) for row in rows]

    async def author_names_for(self, canonical: str) -> list[str]:
        """canonical + 指向它的全部别名（items 查询的展开集合）。"""
        rows = await self._db.fetch_all(
            "SELECT alias FROM author_aliases WHERE canonical = ?",
            (canonical,),
        )
        return [canonical] + [str(row["alias"]) for row in rows]

    async def author_items(
        self, canonical: str, *, limit: int = 20, offset: int = 0
    ) -> list[Any]:
        """某作者（别名折叠后）的条目行（published_at DESC 分页）。"""
        names = await self.author_names_for(canonical)
        placeholders = ", ".join("?" for _ in names)
        await self._db.migrate()
        rows = await self._db.fetch_all(
            f"SELECT entry_ref, title, feed_title, feed_url, author, url, content_text, published_at, read, starred FROM search_entries WHERE author IN ({placeholders}) ORDER BY published_at DESC, id DESC LIMIT ? OFFSET ?",
            (*names, max(1, min(limit, 100)), max(0, offset)),
        )
        return list(rows)

    # -- 别名 ---------------------------------------------------------

    async def create_alias(self, alias: Any, canonical: Any) -> dict[str, Any]:
        clean_alias = _clean_author(alias, "alias")
        clean_canonical = _clean_author(canonical, "canonical")
        if clean_alias == clean_canonical:
            raise AuthorAliasInvalid("别名不能与规范名相同。")
        await self._db.migrate()
        await self._db.execute(
            "INSERT OR REPLACE INTO author_aliases (alias, canonical, created_at) VALUES (?, ?, ?)",
            (clean_alias, clean_canonical, utc_now()),
        )
        row = await self._db.fetch_one(
            "SELECT alias, canonical, created_at FROM author_aliases WHERE alias = ?",
            (clean_alias,),
        )
        assert row is not None
        return {
            "alias": str(row["alias"]),
            "canonical": str(row["canonical"]),
            "createdAt": str(row["created_at"]),
        }

    async def list_aliases(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT alias, canonical, created_at FROM author_aliases ORDER BY created_at DESC, alias ASC",
            (),
        )
        return [
            {
                "alias": str(row["alias"]),
                "canonical": str(row["canonical"]),
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]

    async def delete_alias(self, alias: str) -> bool:
        await self._db.migrate()
        exists = await self._db.fetch_one(
            "SELECT alias FROM author_aliases WHERE alias = ?", (alias,)
        )
        if exists is None:
            return False
        await self._db.execute(
            "DELETE FROM author_aliases WHERE alias = ?", (alias,)
        )
        return True
