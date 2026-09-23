"""Discovery routes (moved verbatim from main.py)."""



from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from lumirss.deps import _get_discovery_service, _get_preview_service, _preview_json
from lumirss.models import (
    FeedPreviewReparseResponse,
    FeedPreviewResult,
    SourceDiscoveryResponse,
)

router = APIRouter()


class FeedPreviewRequest(BaseModel):
    """POST /api/v1/feed-preview body (0013 Gate 2)."""

    feedUrl: str = Field(min_length=1)


@router.post(
    "/api/v1/feed-preview",
    response_model=FeedPreviewResult,
    response_model_exclude_none=False,  # siteUrl/description may be null
)
async def preview_feed(
    body: FeedPreviewRequest, request: Request
) -> dict[str, object]:
    """Preview a direct RSS/Atom URL — strictly NON-MUTATING.

    safe fetch → bounded bytes → offline parse. Reads the FreshRSS
    subscription list (alreadySubscribed) but never writes anything:
    subscribing is POST /api/v1/subscriptions. Only reliable metadata is
    returned — no entries, no scraping, no feed discovery.

    N033：响应附带 encodingInspection（声明/检测/乱码风险 + 掩码样本）；
    若用户保存过 encoding_override，预览解析按该选择解码（只影响 Lumi
    自己的 feed 字节→文本解码点，历史投影数据不回写）。
    """
    from lumirss.source_overrides import SourceOverrideStore

    override = await SourceOverrideStore(request.app.state.db).get_encoding_override(
        body.feedUrl
    )
    service = _get_preview_service(request)
    preview = await service.preview(body.feedUrl, encoding_override=override)
    return _preview_json(preview)


class FeedPreviewReparseBody(BaseModel):
    """POST /api/v1/feed-preview/reparse body (N033).

    encoding=None → 只返回三种选择（utf-8 | declared | detected）的渲染
    对比；encoding+save=true → 把该选择存为来源覆盖（影响后续预览的
    解码方式，绝不回写历史投影）。
    """

    model_config = {"extra": "forbid"}

    feedUrl: str = Field(min_length=1)
    encoding: Literal["utf-8", "declared", "detected"] | None = None
    save: bool = False


@router.post(
    "/api/v1/feed-preview/reparse",
    response_model=FeedPreviewReparseResponse,
    response_model_exclude_none=False,
)
async def reparse_feed(body: FeedPreviewReparseBody, request: Request) -> dict[str, object]:
    """N033 重新解析诊断：同一次有界抓取，三种编码选择各渲染一份
    （title + 掩码样本 + 乱码风险），供用户显式选择。选中的选择可保存
    为 source_overrides.encoding_override（仅影响未来的解码）。"""
    from lumirss.source_overrides import SourceOverrideStore

    stored_override = await SourceOverrideStore(
        request.app.state.db
    ).get_encoding_override(body.feedUrl)
    service = _get_preview_service(request)
    _document, inspection, choices = await service.reparse(
        body.feedUrl,
        encoding_override=body.encoding or stored_override,
    )
    saved: str | None = None
    if body.encoding is not None and body.save:
        await SourceOverrideStore(request.app.state.db).set_encoding_override(
            body.feedUrl, body.encoding
        )
        saved = body.encoding
    return {
        "feedUrl": body.feedUrl,
        "inspection": inspection,
        "choices": choices,
        "applied": body.encoding or stored_override,
        "savedOverride": saved,
    }


class SourceDiscoveryRequest(BaseModel):
    """POST /api/v1/source-discovery body (0014): a public website URL."""

    url: str = Field(min_length=1)


@router.post(
    "/api/v1/source-discovery",
    response_model=SourceDiscoveryResponse,
    response_model_exclude_none=False,  # declared candidates: title/format null
)
async def source_discovery(
    body: SourceDiscoveryRequest, request: Request
) -> dict[str, object]:
    """Discover RSS/Atom feed candidates for a website — NON-MUTATING.

    Safe-fetches ONE page (never crawls), extracts explicit rel=alternate
    declarations, and only when there are none probes a bounded set of
    common feed endpoints. Candidates are not subscribed here — preview is
    POST /api/v1/feed-preview, subscribing is POST /api/v1/subscriptions.
    """
    service = _get_discovery_service(request)
    candidates = await service.discover(body.url)
    return {
        "candidates": [
            {
                "feedUrl": candidate.feed_url,
                "title": candidate.title,
                "source": candidate.source,
                "format": candidate.format,
            }
            for candidate in candidates
        ]
    }


