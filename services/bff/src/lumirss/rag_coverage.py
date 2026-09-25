"""N152 RAG 索引覆盖率 —— 语料 ↔ rag_chunks 的真实分桶盘点。

分桶口径（全部来自真实行/作业，绝无估算）：
- indexable：语料中「有非空正文」的 ref 数（可被分块索引）；语料与
  重建同口径 —— RSS 侧剔除 AI 禁用（F066 严格优先）与 rag_excluded
  （F091）来源，库侧取全部投影行；
- indexed：语料 ref 中在当前模型下有 ≥1 个分块的数量；
- stale：已索引但分块存储的 content_hash ≠ 当前正文 hash（F100 同款
  判定，含缺 hash 的旧行）；
- failed：最近一次 rag_jobs 行 stats.skipped 里的 ref（重建中途源被
  删除而跳过 = 真实作业证据），去重计数；
- unsupported：正文为空的语料行 —— 永远不可能产生分块，按 kind 分组
  并给原因（empty_text）。

纯读：本模块无任何写站点。
"""

from typing import Any

from lumirss.rag import doc_content_hash

# 有界盘点：超大库只统计前 N 行（诚实有界，不做全表 Python 循环）。
_MAX_SWEEP_ROWS = 2000
_MAX_STALE_REFS = 500
_MAX_UNSUPPORTED_KINDS = 20
_UNSUPPORTED_REASON_EMPTY_TEXT = "empty_text"


async def scan_coverage(service: Any) -> dict[str, Any]:
    """对每个用户库做一次语料 vs 索引的覆盖盘点（纯只读）。"""
    db = service._db  # noqa: SLF001 — 同模块族协作
    await db.migrate()
    # N157：分块口径按 LIVE 模型（indexed/stale 都对当前索引负责）。
    from lumirss.rag import DEFAULT_MODEL_ID, live_model_id

    model_id = await live_model_id(db, DEFAULT_MODEL_ID)

    from lumirss.rag_exclusions import rag_excluded_feed_set
    from lumirss.source_ai_gate import ai_disabled_feed_set

    disabled_feeds = await ai_disabled_feed_set(db)
    disabled_feeds = disabled_feeds | await rag_excluded_feed_set(db)

    corpus: dict[str, tuple[str, str]] = {}
    rss_rows = await db.fetch_all(
        "SELECT entry_ref, feed_url, content_text FROM search_entries ORDER BY id LIMIT ?",
        (_MAX_SWEEP_ROWS,),
    )
    for row in rss_rows:
        if str(row["feed_url"] or "") in disabled_feeds:
            continue
        corpus[str(row["entry_ref"])] = ("rss", str(row["content_text"] or ""))
    lib_rows = await db.fetch_all(
        "SELECT ref, kind, body FROM search_library ORDER BY ref LIMIT ?",
        (_MAX_SWEEP_ROWS,),
    )
    for row in lib_rows:
        corpus.setdefault(
            str(row["ref"]), (str(row["kind"] or ""), str(row["body"] or ""))
        )

    chunk_rows = await db.fetch_all(
        "SELECT ref, MIN(content_hash) AS stored_hash FROM rag_chunks WHERE model_id = ? GROUP BY ref",
        (model_id,),
    )
    indexed_hashes = {
        str(row["ref"]): (str(row["stored_hash"]) if row["stored_hash"] else None)
        for row in chunk_rows
    }

    indexable = 0
    unsupported_kinds: dict[str, int] = {}
    stale = 0
    indexed = 0
    # N158：过期 ref 明细（有界）——覆盖率卡片「重建所选」的输入。
    stale_refs: list[str] = []
    for ref, (kind, text) in corpus.items():
        if not text.strip():
            # 空正文：不可索引（unsupported），已不在 indexed 口径内。
            unsupported_kinds[kind] = unsupported_kinds.get(kind, 0) + 1
            continue
        indexable += 1
        stored = indexed_hashes.get(ref)
        if stored is None:
            continue
        indexed += 1
        if stored != doc_content_hash(text):
            stale += 1
            if len(stale_refs) < _MAX_STALE_REFS:
                stale_refs.append(ref)

    failed_refs = await _latest_job_skipped_refs(db)
    return {
        "modelId": model_id,
        "indexable": indexable,
        "indexed": indexed,
        "stale": stale,
        "staleRefs": stale_refs,
        "failed": len(failed_refs),
        "unsupported": {
            "count": sum(unsupported_kinds.values()),
            "kinds": [
                {"kind": kind, "reason": _UNSUPPORTED_REASON_EMPTY_TEXT}
                for kind in sorted(unsupported_kinds)
            ][:_MAX_UNSUPPORTED_KINDS],
        },
    }


async def _latest_job_skipped_refs(db: Any) -> list[str]:
    """最近一次重建作业的 skipped refs（真实作业证据；有界去重）。"""
    import json

    row = await db.fetch_one(
        "SELECT stats_json FROM rag_jobs ORDER BY updated_at DESC, id DESC LIMIT 1"
    )
    if row is None or not row["stats_json"]:
        return []
    try:
        stats = json.loads(str(row["stats_json"]))
    except json.JSONDecodeError:
        return []
    skipped = stats.get("skipped") if isinstance(stats, dict) else None
    if not isinstance(skipped, list):
        return []
    cleaned = [str(r) for r in skipped if r]
    return list(dict.fromkeys(cleaned))[:_MAX_STALE_REFS]
