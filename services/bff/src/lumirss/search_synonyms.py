"""F078 检索同义词 — search_synonyms 存取 + 查询词扩展。

- term UNIQUE（≤50 字符）；expansion ≤8 个、每个 ≤50 字符；enabled 开关；
- 展开规则（诚实单层）：查询词 casefold 相等命中 term → 并入其
  expansions；expansion 即使又是别的 term 也不递归展开；
- 复杂度上限：扩展后有效词总数 ≤100。

全部 SQL 为内联字面量 + 绑定参数；写站点 3 处（insert/update/delete）。
"""

import json as _json
import uuid as _uuid
from typing import Any

from lumirss.util import utc_now

TERM_MAX = 50
EXPANSION_MAX = 50
MAX_EXPANSIONS = 8
MAX_EFFECTIVE_TERMS = 100

_INSERT_SQL = """INSERT INTO search_synonyms (id, term, expansions, enabled, created_at)
VALUES (?, ?, ?, ?, ?)"""

_UPDATE_SQL = """UPDATE search_synonyms SET expansions = ?, enabled = ? WHERE id = ?"""


class SynonymInvalid(ValueError):
    """同义词载荷非法（映射 422）。"""


def _clean_term(term: Any) -> str:
    if not isinstance(term, str):
        raise SynonymInvalid("term must be a string.")
    clean = term.strip()
    if not clean or len(clean) > TERM_MAX:
        raise SynonymInvalid(f"term must be 1..{TERM_MAX} characters.")
    return clean


def _clean_expansions(expansions: Any) -> list[str]:
    if not isinstance(expansions, list) or not expansions:
        raise SynonymInvalid("expansions must be a non-empty array.")
    if len(expansions) > MAX_EXPANSIONS:
        raise SynonymInvalid(f"expansions supports at most {MAX_EXPANSIONS} items.")
    clean = []
    for item in expansions:
        if not isinstance(item, str) or not item.strip() or len(item.strip()) > EXPANSION_MAX:
            raise SynonymInvalid(f"each expansion must be 1..{EXPANSION_MAX} characters.")
        clean.append(item.strip())
    return clean


def _row(row: Any) -> dict[str, Any]:
    try:
        expansions = _json.loads(row["expansions"])
    except _json.JSONDecodeError:
        expansions = []
    return {
        "id": str(row["id"]),
        "term": str(row["term"]),
        "expansions": expansions if isinstance(expansions, list) else [],
        "enabled": bool(row["enabled"]),
        "createdAt": str(row["created_at"]),
    }


class SynonymStore:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def create(self, term: Any, expansions: Any, enabled: bool = True) -> dict[str, Any]:
        clean_term = _clean_term(term)
        clean_expansions = _clean_expansions(expansions)
        await self._db.migrate()
        synonym_id = str(_uuid.uuid4())
        await self._db.execute(
            _INSERT_SQL,
            (synonym_id, clean_term, _json.dumps(clean_expansions, ensure_ascii=False), 1 if enabled else 0, utc_now()),
        )
        row = await self._db.fetch_one("SELECT * FROM search_synonyms WHERE id = ?", (synonym_id,))
        return _row(row)

    async def update(self, synonym_id: str, *, expansions: Any = None, enabled: bool | None = None) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT * FROM search_synonyms WHERE id = ?", (synonym_id,))
        if row is None:
            return None
        current = _row(row)
        clean_expansions = (
            _json.dumps(_clean_expansions(expansions), ensure_ascii=False)
            if expansions is not None
            else _json.dumps(current["expansions"], ensure_ascii=False)
        )
        new_enabled = current["enabled"] if enabled is None else enabled
        await self._db.execute(_UPDATE_SQL, (clean_expansions, 1 if new_enabled else 0, synonym_id))
        updated = await self._db.fetch_one("SELECT * FROM search_synonyms WHERE id = ?", (synonym_id,))
        return _row(updated)

    async def delete(self, synonym_id: str) -> bool:
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT id FROM search_synonyms WHERE id = ?", (synonym_id,))
        if row is None:
            return False
        await self._db.execute("DELETE FROM search_synonyms WHERE id = ?", (synonym_id,))
        return True

    async def list_synonyms(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT * FROM search_synonyms ORDER BY created_at DESC LIMIT 500"
        )
        return [_row(row) for row in rows]

    async def load_enabled_map(self) -> dict[str, list[str]]:
        """enabled 同义词 → casefold(term) → expansions（查询扩展用）。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT term, expansions FROM search_synonyms WHERE enabled = 1"
        )
        result: dict[str, list[str]] = {}
        for row in rows:
            try:
                expansions = _json.loads(row["expansions"])
            except _json.JSONDecodeError:
                continue
            if isinstance(expansions, list):
                result[str(row["term"]).casefold()] = [str(e) for e in expansions]
        return result


def expand_terms(terms: list[str], synonym_map: dict[str, list[str]]) -> list[str]:
    """单层扩展：命中 term（casefold 相等）并入 expansions；去重保序；
    有效词总数 ≤100（复杂度上限）。"""
    out: list[str] = []
    seen: set[str] = set()
    for term in terms:
        folded = term.casefold()
        if folded not in seen:
            out.append(term)
            seen.add(folded)
        for expansion in synonym_map.get(folded, []):
            exp_folded = expansion.casefold()
            if exp_folded in seen or len(out) >= MAX_EFFECTIVE_TERMS:
                continue
            out.append(expansion)
            seen.add(exp_folded)
    return out
