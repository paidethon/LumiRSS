"""Subscriptions routes (moved verbatim from main.py)."""



from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field, ValidationError, model_validator

from lumirss.config import FreshRSSSettings
from lumirss.deps import _get_control_adapter
from lumirss.models import (
    Category,
    FreshRssUiInfo,
    Subscription,
)
from lumirss.subscriptionref import (
    decode_subscription_ref,
)

router = APIRouter()


class SubscriptionCreate(BaseModel):
    """POST /api/v1/subscriptions body.

    feedUrl must be an absolute http(s) URL (validated before FreshRSS);
    categoryId, when given, must exist (404 otherwise); title is optional
    (a blank title is treated as absent — the feed's own title is used).
    """

    feedUrl: str = Field(min_length=1)
    categoryId: str | None = None
    title: str | None = None


class SubscriptionPatch(BaseModel):
    """PATCH /api/v1/subscriptions/{ref} body: move to another category.

    Exactly one target: categoryId (an existing category, 404 when unknown)
    or newCategoryLabel (a new category created by the move itself — the
    only FreshRSS control path that creates categories; conflict-checked
    before any write).
    """

    categoryId: str | None = Field(default=None, min_length=1)
    newCategoryLabel: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def exactly_one_target(self) -> "SubscriptionPatch":
        if (self.categoryId is None) == (self.newCategoryLabel is None):
            raise ValueError(
                "Provide exactly one of 'categoryId' or 'newCategoryLabel'."
            )
        return self


class CategoryPatch(BaseModel):
    """PATCH /api/v1/categories/{categoryId} body: rename the category."""

    label: str = Field(min_length=1)


@router.get(
    "/api/v1/subscriptions",
    response_model=list[Subscription],
    response_model_exclude_none=False,  # uncategorized subscription → null
)
async def subscriptions(request: Request) -> list[dict[str, object]]:
    """Management view of all subscriptions (0013).

    Each item carries the Lumi-owned opaque subscriptionRef (built from
    FreshRSS's feed/<N> stream id — clients never assemble ids themselves)
    plus title/feedUrl/category. The read path (GET /api/v1/feeds) stays
    untouched and compatible.
    """
    control = _get_control_adapter(request)
    return [
        _subscription_json(subscription)
        for subscription in await control.list_subscriptions()
    ]


@router.get("/api/v1/categories", response_model=list[Category])
async def categories(request: Request) -> list[dict[str, str]]:
    """All categories including empty ones (tag/list folders).

    Same id/label contract as the category objects on /api/v1/feeds —
    there is exactly one category model in Lumi.
    """
    control = _get_control_adapter(request)
    return [
        {"id": category.id, "label": category.label}
        for category in await control.list_categories()
    ]


@router.post(
    "/api/v1/subscriptions",
    status_code=201,
    response_model=Subscription,
    response_model_exclude_none=False,
)
async def create_subscription(
    subscription: SubscriptionCreate, request: Request
) -> dict[str, object]:
    """Subscribe to a feed URL; returns the server-confirmed subscription.

    409 when already subscribed (checked before any write); 400 feed_rejected
    when FreshRSS cannot add the feed. The write is attempted exactly once
    (no retry on timeout — clients re-read and reconcile).
    """
    control = _get_control_adapter(request)
    created = await control.subscribe(
        subscription.feedUrl,
        category_id=subscription.categoryId,
        title=subscription.title,
    )
    return _subscription_json(created)


@router.patch("/api/v1/subscriptions/{subscription_ref}", status_code=204)
async def update_subscription(
    subscription_ref: str,
    update: SubscriptionPatch,
    request: Request,
) -> Response:
    """Move one subscription to another category (single-category model).

    Invalid refs and invalid bodies are rejected before any FreshRSS call.
    With newCategoryLabel the move creates the target category (explicit
    create-category path, 0013 Gate 3); with categoryId the target must
    already exist (404 otherwise).
    """
    stream_id = decode_subscription_ref(subscription_ref)  # raises → 400
    control = _get_control_adapter(request)
    if update.newCategoryLabel is not None:
        await control.move_to_new_category(stream_id, update.newCategoryLabel)
    else:
        assert update.categoryId is not None  # exactly-one validator
        await control.move_category(stream_id, update.categoryId)
    return Response(status_code=204)


@router.delete("/api/v1/subscriptions/{subscription_ref}", status_code=204)
async def delete_subscription(
    subscription_ref: str, request: Request
) -> Response:
    """Unsubscribe (destructive; confirmation belongs to the Web UI)."""
    stream_id = decode_subscription_ref(subscription_ref)  # raises → 400
    control = _get_control_adapter(request)
    await control.unsubscribe(stream_id)
    return Response(status_code=204)


@router.patch("/api/v1/categories/{category_id:path}", status_code=204)
async def rename_category(
    category_id: str, update: CategoryPatch, request: Request
) -> Response:
    """Rename one category.

    categoryId is a user/-/label/<名> reference (path converter: slashes in
    the id are fine). 409 category_label_conflict for taken/reserved labels;
    409 default_category_immutable — the FreshRSS default category cannot be
    renamed through the greader API (display name is always re-localized).
    """
    control = _get_control_adapter(request)
    await control.rename_category(category_id, update.label)
    return Response(status_code=204)


@router.get(
    "/api/v1/freshrss-ui",
    response_model=FreshRssUiInfo,
    response_model_exclude_none=False,  # unconfigured → {"url": null}
)
async def freshrss_ui(request: Request) -> dict[str, str | None]:
    """Browser-safe public URL of the FreshRSS web UI, or null.

    The advanced escape hatch ("在 FreshRSS 中管理") is only offered when
    the operator explicitly configured FRESHRSS_PUBLIC_URL. The internal
    FRESHRSS_BASE_URL (possibly a Docker hostname or loopback address) is
    never exposed to the browser, and no URL ever carries credentials.
    """
    try:
        settings = FreshRSSSettings()
    except ValidationError:
        return {"url": None}
    return {"url": settings.FRESHRSS_PUBLIC_URL or None}


def _subscription_json(subscription) -> dict[str, object]:
    return {
        "subscriptionRef": subscription.subscription_ref,
        "title": subscription.title,
        "feedUrl": subscription.feed_url,
        "category": (
            {"id": subscription.category_id, "label": subscription.category_label}
            if subscription.category_id is not None
            and subscription.category_label is not None
            else None
        ),
    }


