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

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.config import RssHubSettings
from lumirss.models import (
    CollectionTiming,
    FreshnessAdvisoryApplyResult,
    FreshnessSuggestionsResponse,
    SourceAccessCardList,
    SourceAccessCardUpdate,
    SourceAccessCardView,
    SourceAliasHistoryItem,
    SourceAliasHistoryList,
    SourceAliasList,
    SourceAliasUpdate,
    SourceAliasView,
    SourceOverrideList,
    SourceOverrideResult,
    SourceOverrideUpdate,
    SourceRegistryEntry,
    SourceRegistryResponse,
    StaleSourcesResponse,
    SubscriptionVolumeItem,
    SubscriptionVolumeResponse,
    VolumeDailyBucket,
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


# ---- N013 来源改名（别名）+ 历史 ---------------------------------------------


@router.get("/api/v1/sources/aliases", response_model=SourceAliasList)
async def list_source_aliases(request: Request) -> SourceAliasList:
    """全部来源别名（时间线/订阅展示的「服务端赢」数据源）。"""
    from lumirss.source_aliases import SourceAliasStore

    items = await SourceAliasStore(request.app.state.db).list_aliases()
    return SourceAliasList(items=[SourceAliasView(**item) for item in items])


@router.put("/api/v1/sources/alias", response_model=SourceAliasView)
async def set_source_alias(payload: SourceAliasUpdate, request: Request) -> SourceAliasView:
    """设置/更名来源别名（upsert；custom_name 变化时写一条历史）。

    upstream_name_at_save = 保存时刻的上游标题快照（适配器不可用 →
    NULL，诚实缺省，绝不阻塞保存）。上游标题变更永不覆盖别名。"""
    from lumirss.deps import _get_adapter
    from lumirss.source_aliases import SourceAliasStore

    upstream_name: str | None = None
    try:
        subscription = next(
            (
                sub
                for sub in await _get_adapter(request).list_subscriptions()
                if sub.feed_url == payload.feedUrl
            ),
            None,
        )
        if subscription is not None:
            upstream_name = subscription.title
    except Exception:  # noqa: BLE001 — 快照尽力而为，不阻塞别名保存
        upstream_name = None
    stored = await SourceAliasStore(request.app.state.db).put_alias(
        payload.feedUrl, payload.customName, upstream_name
    )
    return SourceAliasView(**stored)


@router.get("/api/v1/sources/alias/history", response_model=SourceAliasHistoryList)
async def source_alias_history(
    request: Request, feedUrl: str = Query(min_length=1), limit: int = Query(default=20, ge=1, le=20)
) -> SourceAliasHistoryList:
    """某来源的改名历史（新→旧，≤20；删除别名不删历史）。"""
    from lumirss.source_aliases import SourceAliasStore

    items = await SourceAliasStore(request.app.state.db).history(feedUrl, limit)
    return SourceAliasHistoryList(
        items=[SourceAliasHistoryItem(**item) for item in items]
    )


@router.delete("/api/v1/sources/alias", status_code=204)
async def delete_source_alias(request: Request, feedUrl: str = Query(min_length=1)) -> Response:
    """清除来源别名（历史保留；「恢复旧名」= 用历史名字重新 PUT）。"""
    from lumirss.source_aliases import SourceAliasStore

    await SourceAliasStore(request.app.state.db).delete_alias(feedUrl)
    return Response(status_code=204)


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
    """设置/清除来源覆盖（F11 hiddenUntil / F13 showFrom / F001
    staleAlertHours / N015 muteWindows）。

    sentinel 语义：字段缺席 = 不修改；null = 清除该维度；字符串 =
    设置（接受任意 RFC3339，归一化为 UTC Z；解析失败 → 400）；
    staleAlertHours 为整数小时（1..8760，模型约束外值 → 422）；
    muteWindows 为每周循环静音窗口（days 0-6 子集 + HH:MM 起止，
    end<start 跨午夜，≤7 窗口/来源；非法 → 422）。"""
    from lumirss.mute_windows import set_mute_windows
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
    # N015：分时静音窗口（子集校验，非法 → 422 稳定错误）。
    if "muteWindows" in fields:
        await set_mute_windows(request.app.state.db, payload.feedUrl, payload.muteWindows)
    # N020：关注级别（非法值 → 422 稳定错误；None = 恢复 normal）。
    if "attentionLevel" in fields:
        from lumirss.source_overrides import (
            AttentionLevelInvalid,
            attention_level_valid,
        )

        if payload.attentionLevel is not None and not attention_level_valid(
            payload.attentionLevel
        ):
            raise AttentionLevelInvalid(
                "attentionLevel 必须是 'must_read'、'normal' 或 'low'。"
            )
        await store.set_attention_level(payload.feedUrl, payload.attentionLevel)
    # F066：per-source AI 禁用（服务端执行点统一判定，非仅 UI 隐藏）。
    if "aiDisabled" in fields:
        from lumirss.source_ai_gate import set_ai_disabled

        await set_ai_disabled(request.app.state.db, payload.feedUrl, bool(payload.aiDisabled))
        if payload.aiDisabled:
            await _drop_feed_from_rag(request, payload.feedUrl)
    # N090：per-source 翻译策略（'local_only' | null 清除；缺席=不改）。
    if "translationPolicy" in fields:
        from lumirss.translation_policy import set_translation_policy

        await set_translation_policy(
            request.app.state.db, payload.feedUrl, payload.translationPolicy
        )
    # F032/F034/F031：语言 / 未读警戒阈值 / 同步优先级。
    if "language" in fields or "unreadAlertThreshold" in fields or "syncPriority" in fields:
        metadata_kwargs: dict[str, object] = {}
        if "language" in fields:
            metadata_kwargs["language"] = payload.language
        if "unreadAlertThreshold" in fields:
            metadata_kwargs["unread_alert_threshold"] = payload.unreadAlertThreshold
        if "syncPriority" in fields:
            metadata_kwargs["sync_priority"] = payload.syncPriority
        await store.set_source_metadata(payload.feedUrl, **metadata_kwargs)
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
            "muteWindows": None,
            "attentionLevel": "normal",
            "refreshAdvisory": None,
            "translationPolicy": None,
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
async def subscription_volume(
    request: Request, days: int = 7, daily: bool = False
) -> SubscriptionVolumeResponse:
    """F12 订阅收件量概览（派生投影聚合，只读，不复制 RSS 全文）。

    口径（显式区分，未知为 null 不冒充零）：
    - publishedCount：最近 N 天内「发布时间」落在窗口内的条目数，来自
      search_entries 派生投影（可重建）——投影未覆盖的订阅该值为 null
      （投影落后 ≠ 没有新内容）；
    - lastPublishedAt：该订阅在投影中最新的发布时间；
    - lastSyncedAt：投影最近一次入库时间（fetched_at，秒级时间戳）。

    N040：每项附带 collectionTiming 三时点块——上游发布 / FreshRSS
    收录（crawlTimestampMsec 首次收录，上游不提供 per-entry 周期抓取
    时间，诚实标注口径） / Lumi 投影；latencyHint 指出最大延迟环节。
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
            "SELECT feed_url, MAX(published_at) AS overall_published, MAX(crawled_at) AS overall_crawled, MAX(fetched_at) AS latest_fetched FROM search_entries GROUP BY feed_url"
        )
        # F034：投影口径的每源未读数（search_entries.read=0，派生可重建；
        # 未覆盖 → None，不冒充零）。
        unread_rows = await db.fetch_all(
            "SELECT feed_url, COUNT(*) AS n FROM search_entries WHERE read = 0 GROUP BY feed_url"
        )
        unread_counts = {str(row["feed_url"]): int(row["n"]) for row in unread_rows}
    except Exception:  # noqa: BLE001 — 投影不可用时全部诚实降级为 null
        window_rows = []
        sync_rows = []
        unread_counts = {}
    counts = {
        str(row["feed_url"]): (int(row["n"]), str(row["latest_published"]))
        for row in window_rows
    }
    # F024/F025/F035：daily=true 时附每源按天分桶（发布时间口径，同
    # publishedCount 的派生投影；投影未覆盖的源该值为 None）。日期为
    # UTC 日（published_at 原文即 UTC ISO），窗口内无条目的日期不出现在
    # 数组里——稀疏数组由前端补零渲染。
    daily_buckets: dict[str, list[VolumeDailyBucket]] = {}
    if daily:
        daily_rows = await db.fetch_all(
            "SELECT feed_url, substr(published_at, 1, 10) AS day, COUNT(*) AS n FROM search_entries WHERE published_at >= ? GROUP BY feed_url, substr(published_at, 1, 10)",
            (since,),
        )
        grouped: dict[str, dict[str, int]] = {}
        for row in daily_rows:
            grouped.setdefault(str(row["feed_url"]), {})[str(row["day"])] = int(row["n"])
        daily_buckets = {
            feed_url: [
                VolumeDailyBucket(date=day, count=count)
                for day, count in sorted(days_map.items())
            ]
            for feed_url, days_map in grouped.items()
        }
    timings: dict[str, dict[str, object]] = {}
    for row in sync_rows:
        crawled = row["overall_crawled"]
        projected_epoch = int(row["latest_fetched"]) if row["latest_fetched"] is not None else None
        published = row["overall_published"]
        timing: dict[str, object] = {
            "upstreamPublishedLatest": str(published) if published else None,
            "freshrssFetchedLatest": str(crawled) if crawled else None,
            "freshrssFetchedBasis": (
                "crawlTimestampMsec（FreshRSS 首次收录，非周期抓取时间）"
                if crawled
                else "未提供 by upstream"
            ),
            "lumiProjectedLatest": (
                _epoch_to_iso(projected_epoch) if projected_epoch is not None else None
            ),
            "latencyHint": _latency_hint(published, crawled, projected_epoch),
        }
        timings[str(row["feed_url"])] = timing
    items: list[SubscriptionVolumeItem] = []
    for subscription in subscriptions:
        hit = counts.get(subscription.feed_url)
        timing = timings.get(subscription.feed_url)
        items.append(
            SubscriptionVolumeItem(
                feedUrl=subscription.feed_url,
                title=subscription.title,
                publishedCount=hit[0] if hit else None,
                lastPublishedAt=hit[1] if hit else None,
                lastSyncedAt=(
                    timing["lumiProjectedLatest"] if timing else None
                ),
                collectionTiming=(
                    CollectionTiming(**timing) if timing else None
                ),
                daily=(
                    daily_buckets.get(subscription.feed_url)
                    if daily
                    else None
                ),
                unreadProjected=unread_counts.get(subscription.feed_url),
            )
        )
    return SubscriptionVolumeResponse(
        days=days,
        since=since,
        basis="published_at（search_entries 派生投影，可重建）",
        items=items,
        generatedAt=utc_now(),
    )


def _latency_hint(published, crawled, projected_epoch) -> str | None:
    """N040 最大延迟环节提示（数据不足或全为 0 → None，不臆造）。"""
    from datetime import datetime

    def _parse(value: object) -> datetime | None:
        if not value:
            return None
        try:
            text = str(value).strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    published_dt = _parse(published)
    crawled_dt = _parse(crawled)
    gaps: list[tuple[float, str]] = []
    if published_dt is not None and crawled_dt is not None:
        gaps.append(
            (max(0.0, (crawled_dt - published_dt).total_seconds()), "上游发布→FreshRSS 收录")
        )
    if crawled_dt is not None and projected_epoch is not None:
        gaps.append(
            (
                max(0.0, projected_epoch - crawled_dt.timestamp()),
                "FreshRSS 收录→Lumi 投影",
            )
        )
    if not gaps:
        return None
    seconds, label = max(gaps, key=lambda item: item[0])
    if seconds < 60:
        return None
    if seconds < 3600:
        return f"{label} ≈{int(seconds // 60)} 分钟"
    return f"{label} ≈{seconds / 3600:.1f} 小时"


# ---- N014 自适应低活跃建议 ---------------------------------------------------


class FreshnessAdvisoryApplyBody(BaseModel):
    """POST /api/v1/sources/freshness-suggestions/apply body。"""

    feedUrl: str


@router.get(
    "/api/v1/sources/freshness-suggestions",
    response_model=FreshnessSuggestionsResponse,
)
async def freshness_suggestions(request: Request) -> dict[str, object]:
    """N014：低活跃来源建议（只读；依据 = 派生投影 trailing 8 周画像）。

    对每个订阅计算条目/周（yield）与相邻发布间隔中位数（medianGapDays），
    yield < 0.5 且 gap > 14 天 → 建议「降低刷新频率」。诚实边界：FreshRSS
    greader API 不暴露 per-feed 刷新频率（调度粒度由实例 CRON_MIN 决定），
    因此本端点只产出建议；「应用」= 记录 refreshAdvisory=accepted 决定，
    逐源频率需在 FreshRSS 原生界面调整（/api/v1/freshrss/native-url）。"""
    from datetime import datetime, timedelta

    from lumirss.models import FreshnessSuggestionItem
    from lumirss.source_freshness import (
        SCHEDULING_NOTE,
        TRAILING_WEEKS,
        compute_suggestions,
    )
    from lumirss.source_overrides import SourceOverrideStore

    db = request.app.state.db
    await db.migrate()
    now = datetime.now(UTC)
    cutoff = (now - timedelta(weeks=TRAILING_WEEKS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        window_rows = await db.fetch_all(
            "SELECT feed_url, published_at FROM search_entries WHERE published_at >= ?",
            (cutoff,),
        )
        pre_rows = await db.fetch_all(
            "SELECT feed_url, MAX(published_at) AS published_at FROM search_entries WHERE published_at < ? GROUP BY feed_url",
            (cutoff,),
        )
    except Exception:  # noqa: BLE001 — 投影不可用 → 诚实空建议
        window_rows = []
        pre_rows = []
    suggestions = compute_suggestions(list(window_rows) + list(pre_rows), now=now)
    if not suggestions:
        return {
            "items": [],
            "schedulingNote": SCHEDULING_NOTE,
            "basis": "search_entries 派生投影（published_at，trailing 8 周）",
            "generatedAt": utc_now(),
        }

    feed_urls = {item["feedUrl"] for item in suggestions}
    advisory_map: dict[str, str | None] = {}
    for override in await SourceOverrideStore(db).list_overrides():
        if override["feedUrl"] in feed_urls:
            advisory_map[override["feedUrl"]] = override.get("refreshAdvisory")
    by_url = {
        subscription.feed_url: subscription
        for subscription in await _get_adapter(request).list_subscriptions()
    }
    items: list[FreshnessSuggestionItem] = []
    for item in suggestions:
        subscription = by_url.get(item["feedUrl"])
        if subscription is None:
            continue  # 订阅已退订：建议失效（投影落后是暂态）
        basis = item["basis"]
        items.append(
            FreshnessSuggestionItem(
                feedUrl=item["feedUrl"],
                subscriptionRef=subscription.subscription_ref,
                title=subscription.title,
                currentPattern=item["currentPattern"],
                suggested=item["suggested"],
                basis={
                    "weeks": basis["weeks"],
                    "yield": basis["yield"],
                    "medianGapDays": basis["medianGapDays"],
                },
                refreshAdvisory=advisory_map.get(item["feedUrl"]),
            )
        )
    return {
        "items": items,
        "schedulingNote": SCHEDULING_NOTE,
        "basis": "search_entries 派生投影（published_at，trailing 8 周）",
        "generatedAt": utc_now(),
    }


@router.post(
    "/api/v1/sources/freshness-suggestions/apply",
    response_model=FreshnessAdvisoryApplyResult,
)
async def apply_freshness_advisory(
    body: FreshnessAdvisoryApplyBody, request: Request
) -> dict[str, object]:
    """N014：接受一条低活跃建议 = 在 Lumi 侧记录该决定。

    诚实语义：**不改变任何抓取行为**——FreshRSS greader API 无 per-feed
    ttl/timing 能力，调度粒度由实例 CRON_MIN 决定。记录结果在来源详情
    呈现为「已接受低频建议」；重复接受是幂等的（同值 no-op）。未订阅的
    feed → 404（不为不存在的来源记决定）。"""
    from fastapi.responses import JSONResponse

    from lumirss.source_freshness import SCHEDULING_NOTE
    from lumirss.source_overrides import (
        REFRESH_ADVISORY_ACCEPTED,
        SourceOverrideStore,
    )

    subscribed = any(
        subscription.feed_url == body.feedUrl
        for subscription in await _get_adapter(request).list_subscriptions()
    )
    if not subscribed:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "type": "subscription_not_found",
                    "message": "该来源不在当前账户的订阅中。",
                }
            },
        )
    store = SourceOverrideStore(request.app.state.db)
    await store.set_refresh_advisory(body.feedUrl, REFRESH_ADVISORY_ACCEPTED)
    return {
        "feedUrl": body.feedUrl,
        "refreshAdvisory": REFRESH_ADVISORY_ACCEPTED,
        "schedulingNote": SCHEDULING_NOTE,
    }


# ---- N019 来源接入说明卡 -----------------------------------------------------


@router.get("/api/v1/sources/access-card", response_model=SourceAccessCardView)
async def get_source_access_card(
    request: Request, feedUrl: str = Query(min_length=1, max_length=2048)
) -> dict[str, object]:
    """N019：单个来源的接入说明卡（无卡 → 全 null）。"""
    from lumirss.source_access_cards import SourceAccessCardStore

    return await SourceAccessCardStore(request.app.state.db).get_card(feedUrl)


@router.get("/api/v1/sources/access-cards", response_model=SourceAccessCardList)
async def list_source_access_cards(request: Request) -> dict[str, object]:
    """N019：当前账户全部接入说明卡（per-user 库隔离，只见自己的）。"""
    from lumirss.source_access_cards import SourceAccessCardStore

    items = await SourceAccessCardStore(request.app.state.db).list_cards()
    return {"items": items}


@router.put("/api/v1/sources/access-card", response_model=SourceAccessCardView)
async def put_source_access_card(
    payload: SourceAccessCardUpdate, request: Request
) -> dict[str, object]:
    """N019：整卡 upsert（缺席字段 = 清空该字段）。

    credentialOwnership 只接受归属标签 self/shared/none——**卡里没有
    凭据值字段**（契约上不存在，schema 亦无 secret 列）；未知字段 → 422
    invalid_access_card。"""
    from lumirss.source_access_cards import SourceAccessCardStore

    fields = {
        key: getattr(payload, key)
        for key in ("acquisition", "limits", "credentialOwnership", "maintenance")
        if key in payload.model_fields_set
    }
    return await SourceAccessCardStore(request.app.state.db).put_card(
        payload.feedUrl, fields
    )


# ---- E1: N036 刷新队列可视化 / N037 断更恢复补读 / N038 保留策略预演 -------


class RecoveryToQueueRequest(BaseModel):
    """POST /api/v1/sources/recoveries/{id}/to-queue body（N037）。"""

    model_config = {"extra": "forbid"}

    segment: str | None = None
    """可选：入队行统一落入的分段标签（省略 = 未分组）。"""


class RetentionApplyRequest(BaseModel):
    """POST /api/v1/sources/retention-apply body（N038）。"""

    model_config = {"extra": "forbid"}

    feedUrl: str = Field(min_length=1)
    days: int | None = Field(default=None, ge=7, le=3650)
    """保留天数；null = 清除该来源的保留策略（纯记录，无即时删除）。"""
    prune: bool = False
    """true = 落库后立即按该天数裁剪**本地投影**（starred 恒排除；
    FreshRSS 零调用——见 source_retention 模块诚实边界）。"""


@router.get("/api/v1/sources/refresh-status")
async def sources_refresh_status(request: Request) -> dict[str, object]:
    """N036：每来源最近刷新状态（lastChecked/lastResult/pending + 最近
    5 条检查记录）。

    数据只来自两条写入路径（F050 手动探测 + 投影增量同步的有效交付）；
    没有任何调度器在背后跑（负向契约）。「立即检查」= 复用既有 F050
    探测（POST /api/v1/subscriptions/health-check），不另设端点。"""
    from lumirss.refresh_log import SourceRefreshLogStore

    snapshot = await SourceRefreshLogStore(request.app.state.db).status_snapshot()
    return snapshot


@router.get("/api/v1/sources/recoveries")
async def sources_recoveries(
    request: Request, includeConsumed: bool = True
) -> dict[str, object]:
    """N037：断更恢复窗口列表（error/stale → ok 跳变时由刷新记录路径
    自动创建；consumed=true 表示已加入过补读队列）。"""
    from lumirss.refresh_log import SourceRefreshLogStore

    items = await SourceRefreshLogStore(request.app.state.db).recoveries(
        include_consumed=includeConsumed
    )
    return {"items": items}


@router.post("/api/v1/sources/recoveries/{recovery_id}/to-queue")
async def recovery_to_queue(
    recovery_id: str, payload: RecoveryToQueueRequest, request: Request
) -> dict[str, object]:
    """N037：把恢复窗口内的条目加入今日必读队列（source=recovery）。

    - 一次性消费：consumed=1 原子置位；重复调用 409
      recovery_already_consumed；
    - 逐条走队列既有 add 管线（dedup by ref：同日同条目幂等返回
      existing 行，绝不重复入队/重排）；
    - 条目解析失败的 ref（已删除/退订）诚实跳过并计数（绝不复活）。"""
    from fastapi.responses import JSONResponse

    from lumirss.reading_queue import (
        QueueItemDone,
        ReadingQueueStore,
    )
    from lumirss.refresh_log import (
        RecoveryAlreadyConsumed,
        RecoveryNotFound,
        SourceRefreshLogStore,
    )

    store = SourceRefreshLogStore(request.app.state.db)
    try:
        refs = await store.consume_recovery(recovery_id)
    except RecoveryNotFound:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "type": "recovery_not_found",
                    "message": "恢复窗口不存在。",
                }
            },
        )
    except RecoveryAlreadyConsumed:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "recovery_already_consumed",
                    "message": "该恢复窗口已加入过补读队列。",
                }
            },
        )
    queue = ReadingQueueStore(request.app.state.db)
    added = 0
    duplicates = 0
    skipped = 0
    for ref in refs:
        try:
            _row, outcome = await queue.add_item(
                f"rss:{ref}", payload.segment, source="recovery"
            )
        except QueueItemDone:
            duplicates += 1  # 今日已完成：不再入队（完成状态优先）
            continue
        except Exception:  # noqa: BLE001 — 单条解析失败不中断（诚实跳过）
            skipped += 1
            continue
        if outcome == "created":
            added += 1
        else:
            duplicates += 1
    return {
        "recoveryId": recovery_id,
        "added": added,
        "duplicates": duplicates,
        "skipped": skipped,
        "note": "已加入今日必读队列（source=recovery）；同日同条目幂等，绝不重复入队。",
    }


@router.get("/api/v1/sources/retention-preview")
async def sources_retention_preview(
    request: Request,
    feedUrl: str = Query(min_length=1),
    days: int = Query(default=30, ge=7, le=3650),
) -> dict[str, object]:
    """N038：按来源保留策略预演（只读，投影口径估算）。

    响应以 note 诚实标注：「预估值基于 Lumi 投影，实际删除需在
    FreshRSS 原生界面执行」；freshrssNativeUrl 为 P09 委托入口坐标
    （未绑定 → null）。starred 恒排除并单独计数（绝不进删除路径）。"""
    from lumirss.source_overrides import SourceOverrideStore
    from lumirss.source_retention import retention_preview

    override = await SourceOverrideStore(request.app.state.db).get_override(feedUrl)
    applied = override.get("retentionDays") if override else None
    native_origin: str | None = None
    try:
        await request.app.state.db.migrate()
        row = await request.app.state.db.fetch_one(
            "SELECT public_url FROM freshrss_binding WHERE id = 1"
        )
        if row is not None and row["public_url"]:
            native_origin = str(row["public_url"])
    except Exception:  # noqa: BLE001 — 未绑定诚实降级 null
        native_origin = None
    return await retention_preview(
        request.app.state.db,
        feedUrl,
        days=days,
        applied_days=applied,
        native_origin=native_origin,
    )


@router.post("/api/v1/sources/retention-apply")
async def sources_retention_apply(
    payload: RetentionApplyRequest, request: Request
) -> dict[str, object]:
    """N038：应用保留策略——落库 source_overrides.retention_days，
    可选立即裁剪本地投影（starred 恒排除）。

    **FreshRSS 零调用**（负向契约，测试以适配器 mock 断言）：本端点
    任何一个代码路径都不触上游；retention_days 只驱动派生投影的本地
    裁剪，投影可在下次同步再生（诚实行为，非上游删除替代品）。"""
    from lumirss.source_overrides import (
        SourceOverrideStore,
        retention_days_valid,
    )
    from lumirss.source_retention import prune_projection

    if payload.days is not None and not retention_days_valid(payload.days):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "invalid_retention_days",
                    "message": "retentionDays 必须在 7..3650 之间。",
                }
            },
        )
    store = SourceOverrideStore(request.app.state.db)
    await store.set_retention_days(payload.feedUrl, payload.days)
    pruned = 0
    if payload.prune and payload.days is not None:
        pruned = await prune_projection(
            request.app.state.db, payload.feedUrl, days=payload.days
        )
    return {
        "feedUrl": payload.feedUrl,
        "retentionDays": payload.days,
        "prunedProjectionEntries": pruned,
        "freshrssTouched": False,
        "note": "保留策略只驱动 Lumi 派生投影的本地裁剪；实际删除需在 FreshRSS 原生界面执行。",
    }
