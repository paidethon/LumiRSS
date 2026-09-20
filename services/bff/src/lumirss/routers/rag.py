"""RAG routes (phase2 G7; recovery P0-07): explicit enable/disable,
rebuild, hybrid search, enriched status for the enable/rebuild UI."""

from fastapi import APIRouter, Request

from lumirss.models import (
    RagEnableResult,
    RagExclusionItem,
    RagExclusionList,
    RagExclusionPut,
    RagInconsistencyItem,
    RagInconsistencyList,
    RagRebuildResult,
    RagRepairRequest,
    RagRepairResult,
    RagSearchItem,
    RagSearchResponse,
)
from lumirss.rag import MODEL_ID as MODEL_ID_EXPORT
from lumirss.rag import RagService

from ..deps import _get_rag_service

router = APIRouter()


@router.get("/api/v1/rag/status")
async def rag_status(request: Request) -> dict:
    """Everything the enable/rebuild UI needs: index counts, model
    info, resource state, last error."""
    service: RagService = _get_rag_service(request)
    return await service.status()


@router.post("/api/v1/rag/enable", response_model=RagEnableResult)
async def rag_enable(request: Request) -> RagEnableResult:
    """Explicit user consent to download/load the embedding model.

    Failure is honest: a 503 ``model_unavailable`` envelope with the
    reason also recorded in status.lastError; ``enabled`` stays false."""
    service: RagService = _get_rag_service(request)
    enabled = await service.enable()
    return RagEnableResult(enabled=enabled)


@router.post("/api/v1/rag/disable", response_model=RagEnableResult)
async def rag_disable(request: Request) -> RagEnableResult:
    """Disable the semantic leg and release the model resources."""
    service: RagService = _get_rag_service(request)
    await service.disable()
    return RagEnableResult(enabled=False)


@router.post("/api/v1/rag/rebuild", response_model=RagRebuildResult)
async def rag_rebuild(request: Request) -> RagRebuildResult:
    service: RagService = _get_rag_service(request)
    result = await service.rebuild()
    return RagRebuildResult(**result)


@router.get("/api/v1/rag/search", response_model=RagSearchResponse)
async def rag_search(
    request: Request,
    q: str,
    k: int = 8,
    kind: str | None = None,
) -> RagSearchResponse:
    service: RagService = _get_rag_service(request)
    result = await service.search(q, k=max(1, min(k, 20)), kind=kind)
    return RagSearchResponse(
        items=[
            RagSearchItem(
                ref=item["ref"],
                kind=item["kind"],
                text=item["text"][:400],
                score=round(float(item["score"]), 4),
                title=item.get("title") or None,
                modelId=MODEL_ID_EXPORT,
            )
            for item in result["items"]
        ],
        semanticUsed=result["semanticUsed"],
        semanticError=result["semanticError"],
    )


# ---------------------------------------------------------------------------
# W5: F091 排除 / F092 试检索字段 / F093 作业 / F100 一致性
# ---------------------------------------------------------------------------


@router.get("/api/v1/rag/exclusions", response_model=RagExclusionList)
async def rag_exclusions(request: Request) -> RagExclusionList:
    """F091：来源列表 + 排除状态 + 受影响分块计数预览。"""
    from lumirss.rag_exclusions import list_exclusions

    items = await list_exclusions(request.app.state.db)
    return RagExclusionList(
        items=[
            RagExclusionItem(
                feedUrl=item["feedUrl"],
                ragExcluded=item["ragExcluded"],
                aiDisabled=item["aiDisabled"],
                affectedChunks=item["affectedChunks"],
            )
            for item in items
        ]
    )


@router.put("/api/v1/rag/exclusions", response_model=RagExclusionList)
async def put_rag_exclusion(payload: RagExclusionPut, request: Request) -> RagExclusionList:
    """F091：设置来源排除；排除即移除该源现有分块（mark_stale 路径）。"""
    from lumirss.rag_exclusions import list_exclusions, set_rag_excluded
    from lumirss.source_ai_gate import feed_refs

    from ..deps import _rag_mark_stale

    db = request.app.state.db
    feed_url = payload.feedRef
    await set_rag_excluded(db, feed_url, payload.excluded)
    if payload.excluded:
        refs = await feed_refs(db, feed_url)
        await _rag_mark_stale(request, refs)
    items = await list_exclusions(db)
    return RagExclusionList(
        items=[
            RagExclusionItem(
                feedUrl=item["feedUrl"],
                ragExcluded=item["ragExcluded"],
                aiDisabled=item["aiDisabled"],
                affectedChunks=item["affectedChunks"],
            )
            for item in items
        ]
    )


@router.post("/api/v1/rag/rebuild/pause")
async def rag_rebuild_pause(request: Request):
    """F093：请求暂停（当前批完成后停；游标持久化）。"""
    service: RagService = _get_rag_service(request)
    job_id = await service.pause_rebuild()
    if job_id is None:
        return {"paused": False, "jobId": None}
    return {"paused": True, "jobId": job_id, "status": "pausing"}


@router.post("/api/v1/rag/rebuild/resume", response_model=RagRebuildResult)
async def rag_rebuild_resume(request: Request) -> RagRebuildResult:
    """F093：从持久化游标继续（幂等；重启后仍可续）。"""
    service: RagService = _get_rag_service(request)
    result = await service.resume_rebuild()
    return RagRebuildResult(
        chunks=int(result.get("chunks", 0)),
        elapsedMs=int(result.get("elapsedMs", 0)),
        jobId=result.get("jobId"),
        status=str(result.get("status") or "done"),
    )


@router.get("/api/v1/rag/inconsistencies", response_model=RagInconsistencyList)
async def rag_inconsistencies(request: Request) -> RagInconsistencyList:
    """F100：版本失配清单（content_hash / embedding_model 两种依据）。"""
    from lumirss.rag_consistency import scan_inconsistencies

    result = await scan_inconsistencies(_get_rag_service(request))
    return RagInconsistencyList(
        modelId=result["modelId"],
        items=[
            RagInconsistencyItem(
                ref=item["ref"],
                storedHash=item.get("storedHash"),
                currentHash=item.get("currentHash"),
                basis=item["basis"],
            )
            for item in result["items"]
        ],
    )


@router.post("/api/v1/rag/repair", response_model=RagRepairResult)
async def rag_repair(payload: RagRepairRequest, request: Request) -> RagRepairResult:
    """F100：有界修复（重分块受影响条目；逐项诚实汇报）。"""
    from lumirss.rag_consistency import repair_refs

    result = await repair_refs(_get_rag_service(request), payload.refs)
    return RagRepairResult(
        repaired=result["repaired"],
        failed=result["failed"],
    )
