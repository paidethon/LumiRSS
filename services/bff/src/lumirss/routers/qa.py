"""QA routes — N156 资料冲突对照（纯词法，零模型调用）。

F28 compare_facts（模型裁决）之外的通用补位：不给模型、不做语义判断，
只在句级做纯文本比对（jaccard 重叠 + N082 数字口径 + 日期提取），
把「高度相似但数字/日期/词汇不同」的句子对诚实并列。响应恒带
``basis: "lexical"``——UI 据此声明「基于文本比对，非语义裁决」。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lumirss.models import (
    QaConflictEvidence,
    QaConflictItem,
    QaConflictRequest,
    QaConflictResponse,
)
from lumirss.qa_conflicts import QaConflictInvalid, detect_conflicts

router = APIRouter()


@router.post("/api/v1/qa/conflicts", response_model=QaConflictResponse)
async def qa_conflicts(
    payload: QaConflictRequest, request: Request
) -> QaConflictResponse | JSONResponse:
    """N156：资料冲突对照（≤5 refs、本人范围、纯词法）。

    - refs 去重后需 ≥2 且全部存在于本用户投影（不存在 → 422
      citation_invalid——与 ask 同一捏造引用拦截口径）；
    - 文本收集复用 N154 rag_evidence（rag_chunks 优先，投影回退）；
    - 两两组合做句级词法比对；证据块定位 = quote 所在 rag_chunks.ord
      （无分块回退为正文句序号）；
    - 零模型调用：本端点不 import 任何 provider 设施。"""
    from lumirss.rag import DEFAULT_MODEL_ID, live_model_id
    from lumirss.rag_evidence import collect_evidence_texts

    db = request.app.state.db
    await db.migrate()
    model_id = await live_model_id(db, DEFAULT_MODEL_ID)  # N157 LIVE 口径
    refs = list(dict.fromkeys(payload.refs))
    if len(refs) < 2:
        raise QaConflictInvalid("对照至少需要 2 个引用。")
    missing = [ref for ref in refs if not await _ref_exists(db, ref)]
    if missing:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "citation_invalid",
                    "message": f"引用不存在（可能为捏造引用）：{', '.join(missing[:5])}",
                }
            },
        )

    texts = await collect_evidence_texts(db, refs)
    usable = {ref: text for ref, text in texts.items() if (text or "").strip()}
    if len(usable) < 2:
        raise QaConflictInvalid("至少需要 2 个有正文的引用才能对照。")

    conflicts = detect_conflicts(usable)
    items = [
        QaConflictItem(
            aRef=item["aRef"],
            bRef=item["bRef"],
            aQuote=item["aQuote"],
            bQuote=item["bQuote"],
            diffKind=item["diffKind"],
            aEvidence=await _evidence_for(db, item["aRef"], item["aQuote"], model_id),
            bEvidence=await _evidence_for(db, item["bRef"], item["bQuote"], model_id),
            overlap=item["overlap"],
        )
        for item in conflicts
    ]
    return QaConflictResponse(
        basis="lexical",
        pairsCompared=len(usable) * (len(usable) - 1) // 2,
        conflicts=items,
    )


async def _ref_exists(db, ref: str) -> bool:
    row = await db.fetch_one(
        "SELECT 1 FROM search_entries WHERE entry_ref = ?", (ref,)
    )
    if row is not None:
        return True
    row = await db.fetch_one("SELECT 1 FROM search_library WHERE ref = ?", (ref,))
    return row is not None


async def _evidence_for(db, ref: str, quote: str, model_id: str) -> QaConflictEvidence:
    """quote → 证据块定位：rag_chunks 含该片段的 ord 优先；回退为
    quote 在投影正文中的句序号；都找不到 = None（诚实缺位）。"""
    needle = quote.strip()[:60]
    rows = await db.fetch_all(
        "SELECT ord, text FROM rag_chunks WHERE ref = ? AND model_id = ? ORDER BY ord ASC",
        (ref, model_id),
    )
    if rows:
        for row in rows:
            if needle and needle in str(row["text"] or ""):
                return QaConflictEvidence(ref=ref, blockIndex=int(row["ord"] or 0))
    body_row = await db.fetch_one(
        "SELECT content_text FROM search_entries WHERE entry_ref = ?", (ref,)
    )
    if body_row is None:
        body_row = await db.fetch_one(
            "SELECT body AS content_text FROM search_library WHERE ref = ?", (ref,)
        )
    if body_row is not None and needle:
        from lumirss.qa_conflicts import split_sentences

        for index, sentence in enumerate(split_sentences(str(body_row["content_text"] or ""))):
            if needle in sentence:
                return QaConflictEvidence(ref=ref, blockIndex=index)
    return QaConflictEvidence(ref=ref, blockIndex=None)
