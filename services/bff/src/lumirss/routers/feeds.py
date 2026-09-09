"""Feeds routes (moved verbatim from main.py)."""



from fastapi import APIRouter, Request

from lumirss.deps import _get_adapter
from lumirss.models import (
    Feed,
)

router = APIRouter()


@router.get(
    "/api/v1/feeds",
    response_model=list[Feed],
    response_model_exclude_none=False,  # uncategorized feed → "category": null
)
async def feeds(request: Request) -> list[dict[str, object]]:
    """List feeds from FreshRSS through the FreshRSSAdapter.

    The adapter is created lazily on the first request (settings are only
    read/validated here, never at startup) and then cached on app.state so
    later requests reuse it and its in-memory auth token.

    0011: 每项附带 FreshRSS 真实分类（categoryId 为稳定 key，label 为
    展示名）；无分类的 feed category 为 null（前端归入「未分组」）。
    """
    adapter = _get_adapter(request)
    feeds = await adapter.list_feeds()
    return [
        {
            "title": feed.title,
            "feedUrl": feed.feed_url,
            "category": (
                {"id": feed.category_id, "label": feed.category_label}
                if feed.category_id is not None and feed.category_label is not None
                else None
            ),
        }
        for feed in feeds
    ]


