"""NEW-267 专有名词保护清单 —— 按条目的「当前任务例外」。

N083 的 protect=1 术语默认逐条保留（prompt 指令 + 后处理还原）。
本模块补上例外粒度：

- register：为 (entry_ref, term) 登记例外 —— 该术语在这篇条目的
  后续生成中不再列入保护（其余条目完全不受影响）；幂等（重复登记
  返回既有行）；每篇上限 EXCEPTION_CAP 条；
- remove：显式撤销例外（术语恢复全局默认保护）；
- hits：登记时刻之后的只读命中视图 —— 扫描该篇段缓存行存储的
  source_text，报告每个例外术语命中了多少个不同源段（不发送、
  不改写任何缓存译文）。

语义与「已产生结果不悄悄改变」一致：例外只影响其后的新生成；
既有缓存译文（含其中的保护还原结果）原样展示。

全部 SQL 为内联字面量 + 绑定参数。
"""

import re
import uuid
from dataclasses import dataclass
from typing import Any

from lumirss.util import utc_now

EXCEPTION_CAP = 64

_INSERT_SQL = """INSERT INTO translation_protect_exceptions
(id, entry_ref, term, created_at) VALUES (?, ?, ?, ?)"""

_LIST_SQL = """SELECT term, created_at FROM translation_protect_exceptions
WHERE entry_ref = ? ORDER BY created_at ASC, id ASC"""

_COUNT_SQL = """SELECT COUNT(*) AS total FROM translation_protect_exceptions
WHERE entry_ref = ?"""

_SOURCE_TEXTS_SQL = """SELECT DISTINCT source_text FROM ai_translation_segments
WHERE entry_ref = ? AND source_text IS NOT NULL AND source_text != ''"""


class ProtectTermInvalid(Exception):
    """术语为空或超长 → 422。"""


class ProtectCapExceeded(Exception):
    """每篇例外数超上限 → 422。"""


@dataclass(frozen=True)
class ProtectException:
    term: str
    created_at: str


def _clean_term(term: str) -> str:
    clean = str(term or "").strip()
    if not clean or len(clean) > 200:
        raise ProtectTermInvalid("term 必须是 1..200 字符。")
    return clean


async def register(db: Any, entry_ref: str, term: str) -> ProtectException:
    """登记例外（幂等；超每篇上限 → ProtectCapExceeded）。"""
    await db.migrate()
    clean = _clean_term(term)
    row = await db.fetch_one(
        "SELECT created_at FROM translation_protect_exceptions "
        "WHERE entry_ref = ? AND term = ?",
        (entry_ref, clean),
    )
    if row is not None:
        return ProtectException(clean, str(row["created_at"] or ""))
    count_row = await db.fetch_one(_COUNT_SQL, (entry_ref,))
    if count_row is not None and int(count_row["total"]) >= EXCEPTION_CAP:
        raise ProtectCapExceeded(
            f"At most {EXCEPTION_CAP} protect exceptions per entry."
        )
    now = utc_now()
    await db.execute(
        _INSERT_SQL, (f"tpe-{uuid.uuid4().hex[:16]}", entry_ref, clean, now)
    )
    return ProtectException(clean, now)


async def remove(db: Any, entry_ref: str, term: str) -> bool:
    """撤销例外；未知 → False。"""
    await db.migrate()
    clean = _clean_term(term)
    row = await db.fetch_one(
        "SELECT id FROM translation_protect_exceptions "
        "WHERE entry_ref = ? AND term = ?",
        (entry_ref, clean),
    )
    if row is None:
        return False
    await db.execute(
        "DELETE FROM translation_protect_exceptions WHERE id = ?", (row["id"],)
    )
    return True


async def list_exceptions(db: Any, entry_ref: str) -> list[ProtectException]:
    """该篇全部例外（登记顺序）。"""
    await db.migrate()
    rows = await db.fetch_all(_LIST_SQL, (entry_ref,))
    return [
        ProtectException(str(row["term"]), str(row["created_at"] or ""))
        for row in rows
    ]


async def excluded_terms(db: Any, entry_ref: str) -> set[str]:
    """该篇被豁免的术语集合（供保护映射过滤）。"""
    return {item.term for item in await list_exceptions(db, entry_ref)}


async def exception_hits(db: Any, entry_ref: str) -> list[dict[str, Any]]:
    """只读命中视图：每个例外术语命中多少个不同源段（大小写不敏感，
    与还原后处理同一匹配口径；不改任何行）。"""
    await db.migrate()
    terms = [item.term for item in await list_exceptions(db, entry_ref)]
    if not terms:
        return []
    rows = await db.fetch_all(_SOURCE_TEXTS_SQL, (entry_ref,))
    texts = [str(row["source_text"]) for row in rows]
    result: list[dict[str, Any]] = []
    for term in terms:
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        hit_segments = sum(1 for text in texts if pattern.search(text))
        result.append({"term": term, "hitSegments": hit_segments})
    return result
