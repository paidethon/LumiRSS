"""F100 RAG 版本一致性 —— 失配清单与有界修复。

- 失配判定：分块存储的源文档正文 hash（content_hash，F093 起写入）
  ≠ 当前投影正文 hash（sha256(content_text/body)）；
- 仅元数据变化（标题/标签/来源名）不影响正文 hash → 不列（负向）；
- 模型版本变化（分块 model_id ≠ 当前 MODEL_ID）→ 全部列出并标注
  basis=embedding_model；
- 修复 = 对选中 refs 走既有 index_refs（重分块+重嵌入，原子替换），
  有界（≤50/次）；无失配 → 空清单（诚实空态）。

纯读 + 复用既有写路径：本模块无直接 SQL 写站点。
"""

import hashlib
from typing import Any

from lumirss.rag import MODEL_ID, RagService
from lumirss.util import utc_now

_MAX_INCONSISTENCIES = 100


def _hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


async def scan_inconsistencies(
    service: RagService, *, limit: int = _MAX_INCONSISTENCIES
) -> dict[str, Any]:
    db = service._db  # noqa: SLF001 — 同模块族协作
    await db.migrate()
    # 模型版本变化：非当前模型的分块 → 全部列出（basis=embedding_model）。
    stale_model_rows = await db.fetch_all(
        "SELECT ref, model_id FROM rag_chunks WHERE model_id <> ? GROUP BY ref, model_id LIMIT ?",
        (MODEL_ID, max(1, min(limit, 500))),
    )
    items: list[dict[str, Any]] = [
        {"ref": str(r["ref"]), "storedHash": None, "currentHash": None, "basis": "embedding_model"}
        for r in stale_model_rows
    ]
    if items:
        return {"modelId": MODEL_ID, "items": items[:limit]}

    rows = await db.fetch_all(
        "SELECT c.ref AS ref, MIN(c.content_hash) AS stored_hash, c.model_id AS model_id FROM rag_chunks c WHERE c.model_id = ? GROUP BY c.ref ORDER BY c.ref ASC",
        (MODEL_ID,),
    )
    for row in rows:
        if len(items) >= limit:
            break
        ref = str(row["ref"])
        stored = row["stored_hash"]
        entry = await db.fetch_one(
            "SELECT content_text FROM search_entries WHERE entry_ref = ?", (ref,)
        )
        if entry is not None:
            current_text = str(entry["content_text"] or "")
        else:
            lib = await db.fetch_one(
                "SELECT body FROM search_library WHERE ref = ?", (ref,)
            )
            if lib is None:
                # 源已删除：不属于「版本失配」（孤儿清理走既有 orphan sweep）。
                continue
            current_text = str(lib["body"] or "")
        current = _hash(current_text)
        if stored is None or str(stored) != current:
            items.append(
                {
                    "ref": ref,
                    "storedHash": str(stored) if stored else None,
                    "currentHash": current,
                    "basis": "content_hash",
                }
            )
    return {"modelId": MODEL_ID, "items": items}


async def repair_refs(
    service: RagService, refs: list[str]
) -> dict[str, Any]:
    """修复选中条目（重分块受影响条目，有界 ≤50）；逐项诚实汇报。"""
    cleaned = [str(r) for r in dict.fromkeys(refs) if str(r).strip()][:50]
    repaired: list[str] = []
    failed: list[dict[str, Any]] = []
    for ref in cleaned:
        try:
            result = await service.index_refs([ref])
            if ref in (result.get("missing") or []):
                failed.append({"ref": ref, "reason": "missing"})
            else:
                repaired.append(ref)
        except Exception as exc:  # noqa: BLE001 — 单项失败不影响其余
            failed.append({"ref": ref, "reason": str(exc)[:200]})
    return {"repaired": repaired, "failed": failed, "at": utc_now()}
