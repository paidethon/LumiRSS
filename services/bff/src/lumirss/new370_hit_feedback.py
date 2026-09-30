"""NEW-370 搜索结果评注 —— 「对此问题有用/无关」标记 + 显式排序方案。

语义（负向契约优先）：
- 评注是用户对「某个查询下的某个命中」的显式标记（verdict +
  原因，可重标覆盖）；持久化在 per-user 库，A 的反馈对 B 不可见；
- 反馈绝不自动改变默认搜索排序：默认 GET /search 永远按
  published_at keyset（不信任何反馈信号）；
- 只有一个排序方案「hit_feedback」（有用优先），且默认关闭——
  只有本账户显式 POST ranking-scheme enable 后，reranked 端点才
  返回重排顺序；关闭时 reranked 返回 enabled=false + 空表（诚实）；
- 重排只在本账户命中集合（≤200，keyset 全量迭代）内做稳定重排：
  useful 置顶（按更新时间），其余保持原顺序——顺序可解释。
"""

from typing import Any

from lumirss.search_index import decode_search_cursor, encode_search_cursor
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_REASON = 200
_MAX_QUERY = 200
_COLLECT_CAP = 200
_PAGE = 100
_SCHEME = "hit_feedback"


def query_key(query: str) -> str:
    return " ".join(query.split()).casefold()


class FeedbackEntryMissing(LookupError):
    """entryRef 不在本账户投影（他人/缺失同语义，不泄露存在性）。"""


async def record_feedback(
    db: Database,
    *,
    query: str,
    entry_ref: str,
    verdict: str,
    reason: str | None,
) -> dict[str, Any]:
    """登记/覆盖一条命中评注（必须指向本账户投影内的条目）。"""
    await db.migrate()
    clean_query = " ".join(query.split())[:_MAX_QUERY]
    key = query_key(clean_query)
    clean_reason = (reason or "").strip()[:_MAX_REASON]
    row = await db.fetch_one(
        "SELECT title FROM search_entries WHERE entry_ref = ?", (entry_ref,)
    )
    if row is None:
        raise FeedbackEntryMissing(entry_ref)
    title = str(row["title"])
    now = utc_now()
    existing = await db.fetch_one(
        "SELECT id, created_at FROM search_hit_feedback"
        " WHERE query_key = ? AND entry_ref = ?",
        (key, entry_ref),
    )
    if existing is not None:
        await db.execute(
            "UPDATE search_hit_feedback SET verdict = ?, reason = ?,"
            " updated_at = ? WHERE id = ?",
            (verdict, clean_reason, now, int(existing["id"])),
        )
        return {
            "id": int(existing["id"]),
            "queryKey": key,
            "query": clean_query,
            "entryRef": entry_ref,
            "entryTitle": title,
            "verdict": verdict,
            "reason": clean_reason,
            "createdAt": str(existing["created_at"]),
            "updatedAt": now,
            "already": True,
        }
    new_id = await db.execute(
        "INSERT INTO search_hit_feedback (query_key, query, entry_ref,"
        " entry_title, verdict, reason, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            key,
            clean_query,
            entry_ref,
            title[:200],
            verdict,
            clean_reason,
            now,
            now,
        ),
    )
    return {
        "id": int(new_id or 0),
        "queryKey": key,
        "query": clean_query,
        "entryRef": entry_ref,
        "entryTitle": title,
        "verdict": verdict,
        "reason": clean_reason,
        "createdAt": now,
        "updatedAt": now,
        "already": False,
    }


async def list_feedback(db: Database, *, query: str) -> dict[str, Any]:
    await db.migrate()
    key = query_key(query)
    rows = await db.fetch_all(
        "SELECT id, query, entry_ref, entry_title, verdict, reason,"
        " created_at, updated_at FROM search_hit_feedback"
        " WHERE query_key = ? ORDER BY updated_at DESC LIMIT 200",
        (key,),
    )
    items = [
        {
            "id": int(row["id"]),
            "query": str(row["query"]),
            "entryRef": str(row["entry_ref"]),
            "entryTitle": str(row["entry_title"]),
            "verdict": str(row["verdict"]),
            "reason": str(row["reason"]),
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
        }
        for row in rows
    ]
    useful = sum(1 for item in items if item["verdict"] == "useful")
    return {
        "queryKey": key,
        "items": items,
        "counts": {
            "useful": useful,
            "irrelevant": len(items) - useful,
        },
    }


# -- 排序方案（显式启用；默认关闭） ------------------------------------------


async def scheme_state(db: Database) -> dict[str, Any]:
    await db.migrate()
    row = await db.fetch_one(
        "SELECT scheme, enabled, updated_at FROM search_ranking_settings WHERE id = 1"
    )
    if row is None:
        return {
            "scheme": _SCHEME,
            "enabled": False,
            "updatedAt": None,
            "note": "默认关闭：评注绝不自动改变默认搜索排序。",
        }
    return {
        "scheme": str(row["scheme"]),
        "enabled": bool(row["enabled"]),
        "updatedAt": str(row["updated_at"]),
        "note": "启用后仅 reranked 端点返回有用优先顺序；默认搜索不变。",
    }


async def set_scheme(db: Database, *, enabled: bool) -> dict[str, Any]:
    await db.migrate()
    now = utc_now()
    await db.execute(
        "INSERT INTO search_ranking_settings (id, scheme, enabled, updated_at)"
        " VALUES (1, ?, ?, ?)"
        " ON CONFLICT(id) DO UPDATE SET scheme = excluded.scheme,"
        " enabled = excluded.enabled, updated_at = excluded.updated_at",
        (_SCHEME, int(enabled), now),
    )
    return await scheme_state(db)


async def reranked_hits(
    service: Any, db: Database, *, query: str
) -> dict[str, Any]:
    """显式启用后的「有用优先」重排；关闭时 enabled=false + 空表。"""
    state = await scheme_state(db)
    if not state["enabled"]:
        return {
            **state,
            "items": [],
            "complete": True,
            "note": "排序方案未启用；重排端点不生效（诚实空表）。反馈仍已保存。",
        }
    await db.migrate()
    key = query_key(query)
    feedback_rows = await db.fetch_all(
        "SELECT entry_ref, verdict FROM search_hit_feedback WHERE query_key = ?",
        (key,),
    )
    verdicts = {
        str(row["entry_ref"]): str(row["verdict"]) for row in feedback_rows
    }
    scope = {
        "q": query,
        "feedUrl": None,
        "categoryId": None,
        "unread": False,
        "favorite": False,
        "from": None,
        "to": None,
        "intitle": None,
        "phrase": None,
        "exclude": None,
        "hasSummary": None,
        "author": None,
    }
    ordered: list[str] = []
    keyset = None
    complete = True
    for _ in range(3):  # 2 页 × 100 = 200 上界 + 1 次收尾探测
        result = await service.search(query=query, limit=_PAGE, keyset=keyset)
        for row in result["rows"]:
            ordered.append(str(row["entryRef"]))
        more = bool(result["hasMore"]) and result["nextKeyset"] is not None
        if not more or len(ordered) >= _COLLECT_CAP:
            if more and len(ordered) >= _COLLECT_CAP:
                complete = False
            break
        keyset = decode_search_cursor(
            encode_search_cursor(*result["nextKeyset"], scope=scope),
            scope=scope,
        )
    useful = [ref for ref in ordered if verdicts.get(ref) == "useful"]
    rest = [ref for ref in ordered if verdicts.get(ref) != "useful"]
    return {
        **state,
        "items": [
            {"entryRef": ref, "boosted": ref in set(useful)}
            for ref in useful + rest
        ],
        "complete": complete,
        "note": "有用置顶（按评注更新时间），其余保持原顺序；只在本人命中集合内重排。",
    }
