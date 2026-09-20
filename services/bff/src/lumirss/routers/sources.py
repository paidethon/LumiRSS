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

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from lumirss.config import RssHubSettings
from lumirss.models import (
    SourceOverrideList,
    SourceOverrideResult,
    SourceOverrideUpdate,
    SourceRegistryEntry,
    SourceRegistryResponse,
    StaleSourcesResponse,
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


@router.get("/api/v1/sources/overrides", response_model=SourceOverrideList)
async def list_source_overrides(request: Request) -> SourceOverrideList:
    """F11/F13：当前全部来源级显示覆盖（隐藏期 + 阅读起点）。"""
    from lumirss.source_overrides import SourceOverrideStore

    items = await SourceOverrideStore(request.app.state.db).list_overrides()
    return SourceOverrideList(
        items=[SourceOverrideResult(**item) for item in items]
    )


async def _drop_feed_from_rag(request: Request, feed_url: str) -> None:
    """F066：禁用时把该来源条目从 RAG 索引移除（chunk+向量；
    重新启用后由重建/增量自然恢复纳入）。尽力而为，不阻塞设置写入。"""
    from lumirss.source_ai_gate import feed_refs

    try:
        refs = await feed_refs(request.app.state.db, feed_url)
        if not refs:
            return
        from lumirss.deps import _get_rag_service

        await _get_rag_service(request).mark_stale(refs, wait=False)
    except Exception:  # noqa: BLE001 — 索引清理失败不影响设置写入
        pass


@router.put("/api/v1/sources/overrides", response_model=SourceOverrideResult)
async def set_source_override(payload: SourceOverrideUpdate, request: Request) -> SourceOverrideResult:
    """设置/清除来源覆盖（F11 hiddenUntil / F13 showFrom / F001 staleAlertHours）。

    sentinel 语义：字段缺席 = 不修改；null = 清除该维度；字符串 =
    设置（接受任意 RFC3339，归一化为 UTC Z；解析失败 → 400）；
    staleAlertHours 为整数小时（1..8760，模型约束外值 → 422）。"""
    from lumirss.source_overrides import (
        SourceOverrideStore,
        canonical_utc,
        extract_policy_valid,
        validate_reader_style,
    )

    fields = payload.model_fields_set
    kwargs: dict[str, object] = {}
    if "hiddenUntil" in fields:
        if payload.hiddenUntil is not None and canonical_utc(payload.hiddenUntil) is None:
            from lumirss.library import BookmarkInvalid

            raise BookmarkInvalid("hiddenUntil must be an RFC3339 timestamp.")
        kwargs["hidden_until"] = payload.hiddenUntil
    if "showFrom" in fields:
        if payload.showFrom is not None and canonical_utc(payload.showFrom) is None:
            from lumirss.library import BookmarkInvalid

            raise BookmarkInvalid("showFrom must be an RFC3339 timestamp.")
        kwargs["show_from"] = payload.showFrom
    if "staleAlertHours" in fields:
        kwargs["stale_alert_hours"] = payload.staleAlertHours
    result = await SourceOverrideStore(request.app.state.db).set_fields(
        payload.feedUrl, **kwargs
    )
    store = SourceOverrideStore(request.app.state.db)
    # F048：per-source 正文提取策略。
    if "extractPolicy" in fields:
        if payload.extractPolicy is not None:
            if not extract_policy_valid(payload.extractPolicy):
                from lumirss.library import BookmarkInvalid

                raise BookmarkInvalid("extractPolicy 必须是 'rss' 或 'web'。")
            await store.set_extract_policy(payload.feedUrl, payload.extractPolicy)
        else:
            await store.set_extract_policy(payload.feedUrl, "rss")
    # F055：per-source 阅读样式覆盖（键值子集校验）。
    if "readerStyle" in fields:
        style = validate_reader_style(payload.readerStyle)
        await store.set_reader_style(payload.feedUrl, style)
    # F066：per-source AI 禁用（服务端执行点统一判定，非仅 UI 隐藏）。
    if "aiDisabled" in fields:
        from lumirss.source_ai_gate import set_ai_disabled

        await set_ai_disabled(request.app.state.db, payload.feedUrl, bool(payload.aiDisabled))
        if payload.aiDisabled:
            await _drop_feed_from_rag(request, payload.feedUrl)
    result = await store.get_override(payload.feedUrl)
    if result is None:
        result = {
            "feedUrl": payload.feedUrl,
            "hiddenUntil": None,
            "showFrom": None,
            "staleAlertHours": None,
            "extractPolicy": "rss",
            "readerStyle": None,
            "aiDisabled": False,
            "updatedAt": utc_now(),
        }
    return SourceOverrideResult(**result)


@router.get("/api/v1/sources/stale", response_model=StaleSourcesResponse)
async def stale_sources(
    request: Request,
    threshold: int | None = Query(default=None, ge=1, le=8760),
) -> StaleSourcesResponse:
    """F001：按各自阈值超期的来源列表（只读，无任何写副作用）。

    口径（诚实标注，绝不把发布时间标成抓取成功）：
    - FreshRSS greader subscription/list 在本仓库的适配层不透传
      feed 最近抓取/更新元数据（adapters 现有能力已核实），因此
      basis 恒为 latest_entry（search_entries 派生投影的最新发布时间）
      或 unknown（投影中该 feed 无任何条目——未知 ≠ 超期，不误报）；
    - threshold：全局兜底阈值（小时），仅对未单独配置 staleAlertHours
      的来源生效；缺省时只评估单独配置过的来源。
    """
    from datetime import datetime

    from lumirss.models import StaleSourceItem
    from lumirss.source_overrides import SourceOverrideStore
    from lumirss.util import utc_now

    if threshold is not None and not 1 <= threshold <= 8760:
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "invalid_threshold",
                    "message": "threshold 必须在 1..8760 小时之间。",
                }
            },
        )
    db = request.app.state.db
    configs = await SourceOverrideStore(db).stale_alert_configs()
    adapter = _get_adapter(request)
    subscriptions = await adapter.list_subscriptions()
    now = datetime.now(UTC)

    try:
        rows = await db.fetch_all(
            "SELECT feed_url, MAX(published_at) AS latest_published FROM search_entries GROUP BY feed_url"
        )
    except Exception:  # noqa: BLE001 — 投影不可用 → 全部诚实降级 unknown
        rows = []
    latest = {
        str(row["feed_url"]): str(row["latest_published"])
        for row in rows
        if row["latest_published"] is not None
    }

    items: list[StaleSourceItem] = []
    checked = 0
    for subscription in subscriptions:
        hours = configs.get(subscription.feed_url, threshold)
        if hours is None:
            continue  # 未配置且无全局兜底 → 不评估
        checked += 1
        last_activity = latest.get(subscription.feed_url)
        if last_activity is None:
            continue  # basis=unknown：没有条目证据，绝不判超期
        try:
            last_dt = datetime.fromisoformat(
                last_activity.replace("Z", "+00:00")
            )
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=UTC)
        except ValueError:
            continue  # 无法解析的时间 → 不误报
        age_hours = (now - last_dt).total_seconds() / 3600.0
        if age_hours <= hours:
            continue
        items.append(
            StaleSourceItem(
                feedUrl=subscription.feed_url,
                subscriptionRef=subscription.subscription_ref,
                title=subscription.title,
                staleAlertHours=hours,
                lastActivityAt=last_activity,
                ageHours=round(age_hours, 2),
                basis="latest_entry",
            )
        )
    items.sort(key=lambda item: -(item.ageHours or 0.0))
    return StaleSourcesResponse(items=items, checked=checked, generatedAt=utc_now())


@router.get("/api/v1/sources/replacement-preview")
async def replacement_preview(feedUrl: str, request: Request) -> dict[str, object]:
    """F14：失效来源替换预览——基于既有发现能力，只读。

    从站点 URL 出发找候选 feed（排除当前 feed 自身）；不自动改订阅、
    不判断"失效"（那由 FreshRSS 的 feed error 状态承载）。"""
    from lumirss.deps import _get_discovery_service

    if not feedUrl.startswith(("http://", "https://")):
        return JSONResponse(
            status_code=400,
            content={"error": {"type": "invalid_url", "message": "需要 http(s) URL。"}},
        )
    service = _get_discovery_service(request)
    try:
        candidates = await service.discover(feedUrl)
    except Exception as exc:  # noqa: BLE001 — 发现失败是正常分支
        return JSONResponse(
            status_code=200,
            content={
                "siteUrl": feedUrl,
                "currentFeedUrl": feedUrl,
                "candidates": [],
                "note": f"发现失败：{exc}",
            },
        )
    items = [
        {
            "feedUrl": candidate.feed_url,
            "title": candidate.title or "",
            "kind": candidate.format or candidate.source,
        }
        for candidate in candidates
        if candidate.feed_url != feedUrl
    ]
    return {
        "siteUrl": feedUrl,
        "currentFeedUrl": feedUrl,
        "candidates": items,
        "note": "候选来自页面自动发现；替换需要用户确认后自行操作（本接口不改订阅）。",
    }

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
