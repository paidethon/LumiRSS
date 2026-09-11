"""RAG routes (phase2 G7): explicit enable, rebuild, hybrid search."""

from fastapi import APIRouter, Request

from lumirss.models import (
    RagEnableResult,
    RagRebuildResult,
    RagSearchItem,
    RagSearchResponse,
)
from lumirss.rag import (
    RagModelUnavailable,
    RagRebuildBusy,
    RagService,
)

from ..deps import _get_rag_service

router = APIRouter()


@router.get("/api/v1/rag/status")
async def rag_status(request: Request) -> dict:
    service: RagService = _get_rag_service(request)
    return await service.status()


@router.post("/api/v1/rag/enable", response_model=RagEnableResult)
async def rag_enable(request: Request) -> RagEnableResult:
    """Explicit user consent to download/load the embedding model."""
    service: RagService = _get_rag_service(request)
    enabled = await service.enable()
    return RagEnableResult(enabled=enabled)


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
            )
            for item in result["items"]
        ],
        semanticUsed=result["semanticUsed"],
        semanticError=result["semanticError"],
    )


_ = (RagModelUnavailable, RagRebuildBusy)
