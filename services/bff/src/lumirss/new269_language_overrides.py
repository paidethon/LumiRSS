"""NEW-269 语言识别纠正 —— 用户更正某文/某源的识别语言。

scope='entry'：ref_key=entry_ref（单篇更正）；scope='source'：
ref_key=feed_url（整源更正）。每对 (scope, ref_key) 至多一条 ——
再次更正即覆盖（language/updated_at 更新，created_at 保留首次）。

生效规则（resolve_source_language）：
1. 该篇的 entry 级更正优先；
2. 否则经 search_entries 本地投影找到 feed_url，取该源的更正；
3. 都没有 → None（引擎沿用各自的默认识别：LibreTranslate=auto，
   AI=不附加源语言指令）。

「已产生结果不悄悄改变」：更正绝不改写/失效既有缓存行 —— 只影响
其后的新生成（LibreTranslate 的 source 参数 / AI 引擎的源语言指
令）。缓存身份不变，旧结果原样展示。

全部 SQL 为内联字面量 + 绑定参数。
"""

import re
import uuid
from dataclasses import dataclass
from typing import Any

from lumirss.util import utc_now

MAX_LANGUAGE = 12
_LANGUAGE_RE = re.compile(r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})?$")

_UPSERT_SQL = """INSERT INTO translation_language_overrides
(id, scope, ref_key, language, created_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(scope, ref_key) DO UPDATE SET
language = excluded.language, updated_at = excluded.updated_at"""

_GET_SQL = """SELECT scope, ref_key, language, created_at, updated_at
FROM translation_language_overrides WHERE scope = ? AND ref_key = ?"""

_LIST_SQL = """SELECT scope, ref_key, language, created_at, updated_at
FROM translation_language_overrides ORDER BY updated_at DESC, id DESC"""

_FEED_URL_SQL = "SELECT feed_url FROM search_entries WHERE entry_ref = ?"


class LanguageOverrideInvalid(Exception):
    """更正负载非法（scope/refKey/language）→ 422。"""


@dataclass(frozen=True)
class LanguageOverride:
    scope: str
    ref_key: str
    language: str
    created_at: str
    updated_at: str


def _clean(scope: str, ref_key: str, language: str) -> tuple[str, str, str]:
    clean_scope = str(scope or "").strip()
    if clean_scope not in ("entry", "source"):
        raise LanguageOverrideInvalid("scope 必须是 entry 或 source。")
    clean_ref = str(ref_key or "").strip()
    if not clean_ref or len(clean_ref) > 400:
        raise LanguageOverrideInvalid("refKey 不能为空（≤400 字符）。")
    clean_lang = str(language or "").strip()
    if not clean_lang or len(clean_lang) > MAX_LANGUAGE or not _LANGUAGE_RE.match(clean_lang):
        raise LanguageOverrideInvalid(
            "language 必须是 BCP-47 风格短代码（如 en、zh、zh-CN、pt-BR）。"
        )
    return clean_scope, clean_ref, clean_lang


def _view(row: Any) -> dict[str, Any]:
    return {
        "scope": str(row["scope"]),
        "refKey": str(row["ref_key"]),
        "language": str(row["language"]),
        "createdAt": str(row["created_at"] or ""),
        "updatedAt": str(row["updated_at"] or ""),
    }


async def set_override(
    db: Any, scope: str, ref_key: str, language: str
) -> dict[str, Any]:
    """登记/更正（覆盖旧语言，保留首次 created_at）。"""
    await db.migrate()
    clean_scope, clean_ref, clean_lang = _clean(scope, ref_key, language)
    existing = await db.fetch_one(_GET_SQL, (clean_scope, clean_ref))
    now = utc_now()
    created = str(existing["created_at"]) if existing is not None else now
    await db.execute(
        _UPSERT_SQL,
        (f"tlo-{uuid.uuid4().hex[:16]}", clean_scope, clean_ref, clean_lang, created, now),
    )
    row = await db.fetch_one(_GET_SQL, (clean_scope, clean_ref))
    assert row is not None  # just written
    return _view(row)


async def get_override(db: Any, scope: str, ref_key: str) -> dict[str, Any] | None:
    await db.migrate()
    clean_scope, clean_ref, _lang = _clean(scope, ref_key, "en")
    row = await db.fetch_one(_GET_SQL, (clean_scope, clean_ref))
    return _view(row) if row is not None else None


async def delete_override(db: Any, scope: str, ref_key: str) -> bool:
    """撤销更正（该文/该源回到默认识别）。未知 → False。"""
    await db.migrate()
    clean_scope, clean_ref, _lang = _clean(scope, ref_key, "en")
    row = await db.fetch_one(_GET_SQL, (clean_scope, clean_ref))
    if row is None:
        return False
    await db.execute(
        "DELETE FROM translation_language_overrides WHERE scope = ? AND ref_key = ?",
        (clean_scope, clean_ref),
    )
    return True


async def list_overrides(db: Any) -> list[dict[str, Any]]:
    """本人全部更正（新→旧；per-user 库天然隔离）。"""
    await db.migrate()
    rows = await db.fetch_all(_LIST_SQL)
    return [_view(row) for row in rows]


async def resolve_source_language(db: Any, entry_ref: str) -> str | None:
    """该篇的生效源语言更正（entry 优先 → 源 → None）。"""
    await db.migrate()
    row = await db.fetch_one(_GET_SQL, ("entry", entry_ref))
    if row is not None:
        return str(row["language"])
    feed_row = await db.fetch_one(_FEED_URL_SQL, (entry_ref,))
    if feed_row is None:
        return None
    source_row = await db.fetch_one(
        _GET_SQL, ("source", str(feed_row["feed_url"]))
    )
    return str(source_row["language"]) if source_row is not None else None
