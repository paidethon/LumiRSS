"""Discovery routes (moved verbatim from main.py)."""



from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from lumirss.deps import _get_discovery_service, _get_preview_service, _preview_json
from lumirss.models import (
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
    """
    service = _get_preview_service(request)
    preview = await service.preview(body.feedUrl)
    return _preview_json(preview)


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


