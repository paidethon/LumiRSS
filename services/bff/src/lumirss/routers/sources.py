"""Unified source registry view (0021).

GET /api/v1/sources — one read-only list of every content source LumiRSS
knows about, synthesized AT REQUEST TIME from the owning stores:

    统一 API ≠ 统一数据库.

FreshRSS still owns RSS state, Lumi SQLite owns inbox/api-source/mail
configs, the Obsidian vault stays read-only — this endpoint only
projects their identity + health into one shape so the workbench (and
the read-only agent surface) can enumerate sources without knowing the
storage topology. Secrets are never included; rows carry at most
last-success / last-error health hints that the owning stores already
maintain.
"""

from datetime import UTC

from fastapi import APIRouter, Request

from lumirss.config import RssHubSettings
from lumirss.models import (
    SourceRegistryEntry,
    SourceRegistryResponse,
    SubscriptionVolumeItem,
    SubscriptionVolumeResponse,
)
from lumirss.util import utc_now

from ..deps import (
    _get_adapter,
    _get_api_source_store,
    _get_inbox_store,
    _get_mail_bridge_store,
    _get_obsidian_service,
)

router = APIRouter()


@router.get("/api/v1/sources", response_model=SourceRegistryResponse)
async def list_sources(request: Request) -> SourceRegistryResponse:
    entries: list[SourceRegistryEntry] = []

    # RSS domain — FreshRSS is the engine; its health is the feed fetch
    # path's own concern, so the registry row stays static and honest.
    entries.append(
        SourceRegistryEntry(
            id="freshrss",
            type="rss",
            label="FreshRSS",
            enabled=True,
            summary="RSS/Atom 订阅、条目、已读/收藏的唯一真源",
        )
    )

    rsshub_base = RssHubSettings().RSSHUB_BASE_URL.strip()
    entries.append(
        SourceRegistryEntry(
            id="rsshub",
            type="rsshub",
            label="RSSHub",
            enabled=bool(rsshub_base),
            summary="非 RSS 来源的上游生成器（经 FreshRSS 订阅）",
        )
    )

    api_rows = await _get_api_source_store(request).list_sources()
    for row in api_rows:
        entries.append(
            SourceRegistryEntry(
                id=f"api-source:{row.uuid}",
                type="api_source",
                label=row.name,
                enabled=row.enabled,
                summary="JMESPath → Atom → FreshRSS（条目归 FreshRSS）",
                lastSuccessAt=row.last_success_at,
                lastError=row.last_error,
            )
        )

    mail_lists = await _get_mail_bridge_store(request).list_lists()
    for bridge in mail_lists:
        entries.append(
            SourceRegistryEntry(
                id=f"mail:{bridge.uuid}",
                type="newsletter",
                label=bridge.name,
                enabled=True,
                summary="邮件桥：webhook/IMAP → 摘要 → Atom → FreshRSS",
            )
        )

    obsidian = await _get_obsidian_service(request).get_status()
    env_root = bool(obsidian.get("envRootConfigured"))
    vault_path = str(obsidian.get("vaultPath") or "")
    entries.append(
        SourceRegistryEntry(
            id="obsidian",
            type="obsidian",
            label="Obsidian vault",
            enabled=env_root or bool(vault_path),
            summary="只读单向投影；vault 始终是真源",
            lastSuccessAt=obsidian.get("lastScanAt"),
            lastError=obsidian.get("lastError"),
        )
    )

    inbox_store = _get_inbox_store(request)
    inbox_sources = await inbox_store.list_sources()
    for row in inbox_sources:
        entries.append(
            SourceRegistryEntry(
                id=f"inbox:{row['uuid']}",
                type="inbox",
                label=row["name"],
                enabled=row["enabled"],
                summary="推送式 JSON 收件连接器（api_item 内容归 Lumi）",
                lastSuccessAt=row["lastSuccessAt"],
                lastError=row["lastError"],
            )
        )

    return SourceRegistryResponse(sources=entries, generatedAt=utc_now())


@router.get("/api/v1/sources/volume", response_model=SubscriptionVolumeResponse)
async def subscription_volume(request: Request, days: int = 7) -> SubscriptionVolumeResponse:
    """F12 订阅收件量概览（派生投影聚合，只读，不复制 RSS 全文）。

    口径（显式区分，未知为 null 不冒充零）：
    - publishedCount：最近 N 天内「发布时间」落在窗口内的条目数，来自
      search_entries 派生投影（可重建）——投影未覆盖的订阅该值为 null
      （投影落后 ≠ 没有新内容）；
    - lastPublishedAt：该订阅在投影中最新的发布时间；
    - lastSyncedAt：投影最近一次入库时间（fetched_at，秒级时间戳）。
    """
    from datetime import datetime, timedelta

    def _epoch_to_iso(seconds: int) -> str:
        return datetime.fromtimestamp(seconds, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    days = min(max(days, 1), 30)
    now = datetime.now(UTC)
    since = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    adapter = _get_adapter(request)
    subscriptions = await adapter.list_subscriptions()
    db = request.app.state.db
    await db.migrate()
    try:
        window_rows = await db.fetch_all(
            "SELECT feed_url, COUNT(*) AS n, MAX(published_at) AS latest_published FROM search_entries WHERE published_at >= ? GROUP BY feed_url",
            (since,),
        )
        sync_rows = await db.fetch_all(
            "SELECT feed_url, MAX(fetched_at) AS latest_fetched FROM search_entries GROUP BY feed_url"
        )
    except Exception:  # noqa: BLE001 — 投影不可用时全部诚实降级为 null
        window_rows = []
        sync_rows = []
    counts = {
        str(row["feed_url"]): (int(row["n"]), str(row["latest_published"]))
        for row in window_rows
    }
    synced = {
        str(row["feed_url"]): _epoch_to_iso(int(row["latest_fetched"]))
        for row in sync_rows
        if row["latest_fetched"] is not None
    }
    items: list[SubscriptionVolumeItem] = []
    for subscription in subscriptions:
        hit = counts.get(subscription.feed_url)
        items.append(
            SubscriptionVolumeItem(
                feedUrl=subscription.feed_url,
                title=subscription.title,
                publishedCount=hit[0] if hit else None,
                lastPublishedAt=hit[1] if hit else None,
                lastSyncedAt=synced.get(subscription.feed_url),
            )
        )
    return SubscriptionVolumeResponse(
        days=days,
        since=since,
        basis="published_at（search_entries 派生投影，可重建）",
        items=items,
        generatedAt=utc_now(),
    )
