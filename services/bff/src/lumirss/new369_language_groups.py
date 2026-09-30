"""NEW-369 个人资料语言筛选 —— 按「明确记录或用户校正」的语言分组。

语义（负向契约：绝不靠界面语言或文本特征猜测）：
- 语言只来自显式记录，优先级：
  1. translation_language_overrides scope='entry'（用户对该篇的更正）；
  2. translation_language_overrides scope='source'（对该源的更正）；
  3. source_overrides.language（来源上明确记录的语言）；
  4. 都没有 → unknown（未知语言单独成组呈现，绝不并入任何语言组）；
- 分组只统计实际命中（与 GET /search 同一过滤链，keyset 全量迭代
  ≤2000 条，触界 honest 截断标注）；
- 分组是筛选用途：每组给计数与 refs 样例（≤20），客户端把
  language 组再交给 GET /search 的作者/来源等既有过滤组合渲染。

per-user：投影、更正表、来源覆盖都在 per-user 库，A 的分组对 B 不可见。
"""

from typing import Any

from lumirss.search_index import decode_search_cursor, encode_search_cursor

_COLLECT_CAP = 2000
_PAGE = 250
_SAMPLE_CAP = 20
_MAX_LANG = 12


async def _entry_language(
    db: Any, *, entry_ref: str, caches: dict[str, dict[str, str]]
) -> str | None:
    """显式语言解析（entry 更正 → 源更正 → 源记录 → None=未知）。"""
    if entry_ref in caches["entry"]:
        return caches["entry"][entry_ref]
    row = await db.fetch_one(
        "SELECT language FROM translation_language_overrides"
        " WHERE scope = 'entry' AND ref_key = ?",
        (entry_ref,),
    )
    language = str(row["language"])[:_MAX_LANG] if row else None
    caches["entry"][entry_ref] = language or ""
    return language


async def _source_language(
    db: Any, *, feed_url: str, caches: dict[str, dict[str, str]]
) -> str | None:
    if feed_url in caches["source"]:
        return caches["source"][feed_url] or None
    language: str | None = None
    row = await db.fetch_one(
        "SELECT language FROM translation_language_overrides"
        " WHERE scope = 'source' AND ref_key = ?",
        (feed_url,),
    )
    if row:
        language = str(row["language"])[:_MAX_LANG]
    else:
        row = await db.fetch_one(
            "SELECT language FROM source_overrides WHERE feed_url = ?",
            (feed_url,),
        )
        if row and row["language"]:
            language = str(row["language"])[:_MAX_LANG]
    caches["source"][feed_url] = language or ""
    return language


async def language_groups(
    service: Any, db: Any, *, params: dict[str, Any]
) -> dict[str, Any]:
    """同一过滤链的全量迭代（≤2000）+ 显式语言分组（unknown 独立）。"""
    store = service.store
    await store.ensure_migrated()
    query: str = params["query"]
    scope = {
        "q": query,
        "feedUrl": params["feed_url"],
        "categoryId": params["category_id"],
        "unread": params["unread_only"],
        "favorite": params["starred_only"],
        "from": params["published_from"],
        "to": params["published_to"],
        "intitle": params["intitle"],
        "phrase": params["phrase"],
        "exclude": params["exclude"],
        "hasSummary": params["has_summary"],
        "author": params["author"],
    }
    caches: dict[str, dict[str, str]] = {"entry": {}, "source": {}}
    counts: dict[str, int] = {}
    unknown = 0
    samples: dict[str, list[str]] = {}
    refs: list[str] = []
    keyset = None
    complete = True
    for _ in range(9):  # 8 页 × 250 = 2000 上界 + 1 次收尾探测
        result = await service.search(
            query=query,
            limit=_PAGE,
            keyset=keyset,
            feed_url=params["feed_url"],
            category_id=params["category_id"],
            unread_only=params["unread_only"],
            starred_only=params["starred_only"],
            published_from=params["published_from"],
            published_to=params["published_to"],
            intitle=params["intitle"],
            phrase=params["phrase"],
            exclude=params["exclude"],
            has_summary=params["has_summary"],
            author=params["author"],
            expand_synonyms=False,
        )
        rows = result["rows"]
        for row in rows:
            entry_ref = str(row["entryRef"])
            feed_url = str(row["feedUrl"])
            language = await _entry_language(
                db, entry_ref=entry_ref, caches=caches
            )
            if language is None or language == "":
                language = await _source_language(
                    db, feed_url=feed_url, caches=caches
                )
            key = language if language else "unknown"
            if key == "unknown":
                unknown += 1
            else:
                counts[key] = counts.get(key, 0) + 1
            refs.append(entry_ref)
            bucket = samples.setdefault(key, [])
            if len(bucket) < _SAMPLE_CAP:
                bucket.append(entry_ref)
        more = bool(result["hasMore"]) and result["nextKeyset"] is not None
        if not more or len(refs) >= _COLLECT_CAP:
            if more and len(refs) >= _COLLECT_CAP:
                complete = False  # 触界：诚实标注（不静默截断计数）
            break
        keyset = decode_search_cursor(
            encode_search_cursor(*result["nextKeyset"], scope=scope),
            scope=scope,
        )
    groups = [
        {"language": language, "count": count, "sampleRefs": samples.get(language, [])}
        for language, count in sorted(
            counts.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    return {
        "total": len(refs),
        "complete": complete,
        "groups": groups,
        "unknown": {
            "count": unknown,
            "sampleRefs": samples.get("unknown", []),
        },
        "note": (
            "语言只来自用户更正（entry/source）或来源上明确记录的语言；"
            "无记录一律进 unknown 单独呈现，绝不按界面语言猜测。"
        ),
    }
