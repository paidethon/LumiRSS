"""Subscriptions routes (moved verbatim from main.py)."""



import time

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from lumirss.deps import _get_control_adapter
from lumirss.models import (
    BatchMoveItem,
    BatchMoveRequest,
    BatchMoveResult,
    Category,
    DuplicateSuspectGroup,
    DuplicateSuspectsResponse,
    FreshRssNativeUrl,
    FreshRssUiInfo,
    SourceNotesList,
    SourceNotesUpdate,
    SourceNotesView,
    Subscription,
)
from lumirss.subscriptionref import (
    InvalidSubscriptionReference,
    decode_subscription_ref,
)
from lumirss.util import utc_now

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


async def _source_cap_denial(request: Request) -> JSONResponse | None:
    """N191：订阅前的事前来源上限检查（管理员策略包）。

    计数 = 当前用户投影 search_feeds 的真实行数（本地、无上游请求）；
    无策略行 / 未设 maxSources = 放行。超额 → 429 quota_exceeded
    （带 maxSources / current 事实字段，绝无 retry 语义——上限不随
    时间重置）。任何 store 故障都不放行也不 500 化订阅路径：故障时
    如实放行并在日志留痕（额度执行是 best-effort 边界，绝不能把
    「计数不可用」变成全员无法订阅）。"""
    from lumirss.user_quotas import UserQuotaStore
    from lumirss.user_scope import current_user_id

    uid = current_user_id()
    if not uid:
        return None
    try:
        caps = await UserQuotaStore(request.app.state.control_db).caps_for(uid)
    except Exception:  # noqa: BLE001 — 计数故障不阻断订阅主路径
        return None
    max_sources = caps.get("maxSources")
    if not max_sources:
        return None
    await request.app.state.db.migrate()
    row = await request.app.state.db.fetch_one("SELECT COUNT(*) AS n FROM search_feeds", ())
    current = int(row["n"]) if row else 0
    if current < max_sources:
        return None
    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "type": "quota_exceeded",
                "message": (
                    f"已达到管理员设置的来源上限（{current}/{max_sources}）。"
                    "如需增加订阅来源，请联系运营者调整额度策略。"
                ),
                "maxSources": max_sources,
                "current": current,
            }
        },
    )


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
) -> dict[str, object] | JSONResponse:
    """Subscribe to a feed URL; returns the server-confirmed subscription.

    409 when already subscribed (checked before any write); 400 feed_rejected
    when FreshRSS cannot add the feed. The write is attempted exactly once
    (no retry on timeout — clients re-read and reconcile).

    N191：管理员策略包（user_quotas.maxSources）在此事前拦截——按当前
    用户投影 search_feeds 计数，第 N+1 个来源直接 429 quota_exceeded，
    FreshRSS 侧零请求；成员没有任何路径可以提升该上限（设置端点是
    admin-only，且本路由执行不读任何客户端提供的上限）。
    """
    denial = await _source_cap_denial(request)
    if denial is not None:
        return denial
    control = _get_control_adapter(request)
    matched = _matched_catalog_route(subscription.feedUrl)
    started = time.monotonic()
    try:
        created = await control.subscribe(
            subscription.feedUrl,
            category_id=subscription.categoryId,
            title=subscription.title,
        )
    except Exception as exc:
        # N025：失败的订阅尝试也进路由时间线（FreshRSS 侧会抓取 feed，
        # 失败即一次真实的上游尝试）。分类复用 F050 词汇表。
        if matched is not None:
            await _record_route_run(
                request,
                matched,
                status="failed",
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                failure_class=_subscribe_failure_class(exc),
            )
        raise
    if matched is not None:
        await _record_route_run(
            request,
            matched,
            status="ok",
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            failure_class=None,
        )
        await _record_route_use(request, matched)
    return _subscription_json(created)


class _RouteUse:
    """One catalog route derived server-side from a feed URL path."""

    __slots__ = ("template_id", "route_key", "params")

    def __init__(
        self, template_id: str, route_key: str, params: dict[str, str]
    ) -> None:
        self.template_id = template_id
        self.route_key = route_key
        self.params = params


def _matched_catalog_route(feed_url: str) -> _RouteUse | None:
    """从 feedUrl 路径反推 Lumi 目录路由（不信任客户端上报）。"""
    import urllib.parse

    from lumirss.rsshub import match_route_path
    from lumirss.rsshub_route_store import compute_route_key

    path = urllib.parse.urlsplit(feed_url).path
    matched = match_route_path(path)
    if matched is None:
        return None
    route, params = matched
    return _RouteUse(route.id, compute_route_key(route.id, params), params)


def _subscribe_failure_class(exc: Exception) -> str | None:
    """订阅失败 → F050 词汇表的稳定分类（其余异常不强行归类）。"""
    from lumirss.adapters.freshrss import AuthenticationError, UpstreamConnectionError

    if isinstance(exc, AuthenticationError):
        return "auth_error"
    if isinstance(exc, UpstreamConnectionError):
        return "network_error"
    return None


async def _record_route_use(request: Request, matched: _RouteUse) -> None:
    """N021：成功订阅命中的目录路由 → 最近使用（参数在 store 内统一
    脱敏；元数据写入失败不影响订阅结果——只记日志）。"""
    from lumirss.rsshub_route_store import RssHubRouteStore

    try:
        await RssHubRouteStore(request.app.state.db).record_recent(
            template_id=matched.template_id,
            params=matched.params,
            success=True,
        )
    except Exception:  # noqa: BLE001 — metadata only, never fail the use
        import logging

        logging.getLogger(__name__).exception(
            "rsshub route recent-recording failed on subscribe"
        )


async def _record_route_run(
    request: Request,
    matched: _RouteUse,
    *,
    status: str,
    duration_ms: int,
    failure_class: str | None,
) -> None:
    """N025：订阅尝试的时间线写入（best-effort，失败只记日志）。"""
    from lumirss.rsshub_route_store import RssHubRouteStore

    try:
        await RssHubRouteStore(request.app.state.db).record_run(
            route_key=matched.route_key,
            status=status,
            duration_ms=duration_ms,
            entry_count=None,
            failure_class=failure_class,
        )
    except Exception:  # noqa: BLE001 — metadata only, never fail the use
        import logging

        logging.getLogger(__name__).exception(
            "rsshub route run-recording failed on subscribe"
        )


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


def _adapter_error_code(exc: Exception) -> str:
    """AdapterError → 稳定短错误码（per-item 汇报用）。"""
    from lumirss.adapters.freshrss import (
        AdapterError,
        AuthenticationError,
        UpstreamConnectionError,
    )
    from lumirss.adapters.freshrss_control import (
        CategoryNotFound,
        SubscriptionNotFound,
    )

    if isinstance(exc, CategoryNotFound):
        return "category_not_found"
    if isinstance(exc, SubscriptionNotFound):
        return "subscription_not_found"
    if isinstance(exc, UpstreamConnectionError):
        return "connection_error"
    if isinstance(exc, AuthenticationError):
        return "authentication_error"
    if isinstance(exc, AdapterError):
        return "upstream_error"
    return "unexpected_error"


@router.post("/api/v1/subscriptions/batch-move", response_model=BatchMoveResult)
async def batch_move_subscriptions(
    payload: BatchMoveRequest, request: Request
) -> dict[str, object]:
    """F006：批量分类迁移（逐项执行、逐项汇报；失败不中断整批）。

    语义（文档化）：refs 只包含本次请求显式给定的订阅——「跨页选择」
    由前端只提交当前选中的 refs（不全库隐含）；同一 ref 重复出现只执行
    一次（幂等：移动到已所在分类是 no-op）。targetCategoryId 必须已存在
    （新建分类走既有单移动的 newCategoryLabel 通道）。"""
    control = _get_control_adapter(request)
    items: list[BatchMoveItem] = []
    moved = 0
    seen: set[str] = set()
    for ref in payload.refs:
        if ref in seen:
            continue  # 重复提交同一 ref：只执行一次
        seen.add(ref)
        try:
            stream_id = decode_subscription_ref(ref)
        except InvalidSubscriptionReference:
            items.append(BatchMoveItem(ref=ref, ok=False, error="invalid_ref"))
            continue
        try:
            await control.move_category(stream_id, payload.targetCategoryId)
        except Exception as exc:  # noqa: BLE001 — 逐项失败诚实汇报
            items.append(
                BatchMoveItem(ref=ref, ok=False, error=_adapter_error_code(exc))
            )
            continue
        moved += 1
        items.append(BatchMoveItem(ref=ref, ok=True))
    return {"items": items, "moved": moved}


@router.get("/api/v1/subscriptions/duplicate-suspects", response_model=DuplicateSuspectsResponse)
async def duplicate_suspects(request: Request) -> DuplicateSuspectsResponse:
    """F004：重复订阅候选（只读；只展示，无删除/合并副作用）。

    受控规范化（见 lumirss.url_normalize）：小写 host、去尾斜杠、忽略
    http/https、丢弃已知追踪参数（utm_*/fbclid/gclid 等）；签名参数绝不
    丢弃、路径不同绝不合并（保守，宁可漏报不误报）。"""
    from lumirss.duplicate_suspects import find_duplicate_suspects

    control = _get_control_adapter(request)
    subscriptions = await control.list_subscriptions()
    groups = find_duplicate_suspects(subscriptions)
    return DuplicateSuspectsResponse(
        groups=[
            DuplicateSuspectGroup(
                key=group.key,
                members=[
                    {
                        "subscriptionRef": m.subscription_ref,
                        "title": m.title,
                        "feedUrl": m.feed_url,
                        "categoryLabel": m.category_label,
                    }
                    for m in group.members
                ],
                differences=group.differences,
            )
            for group in groups
        ],
        checked=len(subscriptions),
    )


@router.get("/api/v1/subscriptions/notes", response_model=SourceNotesList)
async def list_source_notes(
    request: Request,
    note_search: str | None = Query(default=None, max_length=200),
) -> dict[str, object]:
    """F005：备注列表（可选 note_search 关键词子串过滤，后端执行）。"""
    from lumirss.source_notes import SourceNotesStore

    items = await SourceNotesStore(request.app.state.db).search_notes(note_search)
    return {"items": [SourceNotesView(**item) for item in items]}


@router.get("/api/v1/subscriptions/{subscription_ref}/notes", response_model=SourceNotesView)
async def get_source_notes(
    subscription_ref: str, request: Request
) -> dict[str, object]:
    """F005：单个订阅的备注/理由/维护记录（无记录 → 全 null）。"""
    from lumirss.source_notes import SourceNotesStore

    return await SourceNotesStore(request.app.state.db).get_notes(subscription_ref)


@router.patch("/api/v1/subscriptions/{subscription_ref}/notes", response_model=SourceNotesView)
async def update_source_notes(
    subscription_ref: str,
    update: SourceNotesUpdate,
    request: Request,
) -> dict[str, object]:
    """F005：更新备注/理由/维护记录（sentinel：缺席=不改，null=清空）。

    存原文不消毒——XSS 由 Web 渲染层转义（React 默认转义），与
    「Article HTML: transforms → DOMPurify」管线无关（本字段不进文章管线）。"""
    from lumirss.source_notes import SourceNotesStore

    kwargs: dict[str, object] = {}
    for field_name in ("note", "reason", "maintenanceLog"):
        if field_name in update.model_fields_set:
            kwargs[field_name] = getattr(update, field_name)
    return await SourceNotesStore(request.app.state.db).update_notes(
        subscription_ref,
        **{
            {
                "note": "note",
                "reason": "reason",
                "maintenanceLog": "maintenance_log",
            }[field_name]: value
            for field_name, value in kwargs.items()
        },
    )


@router.get("/api/v1/subscriptions/{subscription_ref}/unsubscribe-preview")
async def unsubscribe_preview(subscription_ref: str, request: Request) -> Response:
    """N012 退订影响预览（只读，200 先于任何 mutation）。

    汇总该来源条目牵连的 Lumi 自有数据：工作区引用行 / 看板状态行 /
    RSS 书签 / 批注 / 投影未读数 / 会命中的收件箱 source 规则。计数
    如实、样本有界（≤50）。本端点零写入——预览后数据库逐字节不变
    （测试固定该负向契约）。"""
    from fastapi.responses import JSONResponse

    from lumirss.unsubscribe_preview import build_preview

    try:
        stream_id = decode_subscription_ref(subscription_ref)
    except InvalidSubscriptionReference:
        return JSONResponse(
            status_code=400,
            content={"error": {"type": "invalid_subscription_ref", "message": "订阅引用无效。"}},
        )
    control = _get_control_adapter(request)
    subscription = next(
        (sub for sub in await control.list_subscriptions() if sub.stream_id == stream_id),
        None,
    )
    if subscription is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "subscription_not_found", "message": "订阅不存在。"}},
        )
    preview = await build_preview(
        request.app.state.db, subscription.feed_url, subscription.title or ""
    )
    return JSONResponse(
        status_code=200,
        content={
            "subscriptionRef": subscription_ref,
            **preview,
            "note": "预览为只读快照；取消订阅需在界面确认后另行发起。",
        },
    )


@router.delete("/api/v1/subscriptions/{subscription_ref}", status_code=204)
async def delete_subscription(
    subscription_ref: str,
    request: Request,
    keep_artifacts: bool | None = Query(default=None),
) -> Response:
    """Unsubscribe (destructive; confirmation belongs to the Web UI).

    F005：Lumi 侧备注/维护记录同步级联删除（见 0037 迁移注释）——
    FreshRSS RSS 域数据不在此路径触碰。

    N012 keep_artifacts（可选；缺席 = 既有行为原样保留）：
    - true：退订后保留工作区引用 / 看板状态 / 批注（引用冻结 ref，
      解析层已把缺失条目降级为 stale 卡片，不丢用户整理结构）；
    - false：显式清理——批注与该来源条目的工作区引用/看板状态一并
      删除（library 书签保留；清理计数诚实返回 200 语义由响应体承载）。
    确认责任在客户端（预览 + 二次确认），服务端只执行声明过的语义。"""
    stream_id = decode_subscription_ref(subscription_ref)  # raises → 400
    control = _get_control_adapter(request)
    await control.unsubscribe(stream_id)
    from lumirss.source_notes import SourceNotesStore

    await SourceNotesStore(request.app.state.db).delete_notes(subscription_ref)
    if keep_artifacts is not False:
        # 缺席（legacy，逐字节既有行为）与显式 true：保留工作区引用 /
        # 看板状态 / 批注——它们引用冻结 ref，解析层已把缺失条目降级为
        # stale 卡片（workspaces.resolve_refs）。零额外清理。
        return Response(status_code=204)
    # 显式 false：在该来源条目上做显式清理（批注 + 工作区引用/看板状态）。
    from fastapi.responses import JSONResponse

    from lumirss.unsubscribe_preview import purge_feed_artifacts

    feed_url: str | None = None
    try:
        subscription = next(
            (sub for sub in await control.list_subscriptions() if sub.stream_id == stream_id),
            None,
        )
    except Exception:  # noqa: BLE001 — 退订已成功；清理尽力而为
        subscription = None
    feed_url = subscription.feed_url if subscription is not None else None
    purged = await purge_feed_artifacts(request.app.state.db, feed_url or "")
    return JSONResponse(
        status_code=200,
        content={
            "subscriptionRef": subscription_ref,
            "purged": purged,
            "note": "批注与该来源的工作区引用/看板状态已清理；library 书签保留。",
        },
    )


class HealthCheckRequest(BaseModel):
    """POST /api/v1/subscriptions/health-check body (F050)。"""

    model_config = {"extra": "forbid"}

    refs: list[str] = Field(min_length=1, max_length=50)
    timeoutS: float = Field(default=5.0, ge=1.0, le=10.0)


@router.post("/api/v1/subscriptions/health-check")
async def health_check(payload: HealthCheckRequest, request: Request) -> Response:
    """F050 批量检查台：并发 ≤4 探测每源 feed URL（HEAD 失败降级有界 GET
    ≤256KB）。纯诊断——结果不写任何配置（负向契约由测试固定）。

    分类：ok / auth_error / not_found / rate_limited / timeout /
    bad_content / network_error；重复 ref 去重（保持首个）。"""
    import asyncio as _asyncio

    from fastapi.responses import JSONResponse

    seen: set[str] = set()
    refs: list[str] = []
    for ref in payload.refs:
        if ref not in seen:
            seen.add(ref)
            refs.append(ref)
    control = _get_control_adapter(request)
    try:
        subscriptions = await control.list_subscriptions()
    except Exception as exc:  # noqa: BLE001 — 上游不可用如实上报
        return JSONResponse(
            status_code=502,
            content={"error": {"type": "upstream_unavailable", "message": str(exc)}},
        )
    by_ref = {sub.subscription_ref: sub for sub in subscriptions}

    injected = getattr(request.app.state, "health_probe", None)

    async def probe(ref: str) -> dict[str, object]:
        checked_at = utc_now()
        sub = by_ref.get(ref)
        if sub is None:
            return {"ref": ref, "status": "not_found", "checkedAt": checked_at}
        if injected is not None:
            result = await injected(sub.feed_url, payload.timeoutS)
        else:
            result = await _probe_feed_url(
                sub.feed_url,
                payload.timeoutS,
                http_client=getattr(request.app.state, "http_client", None),
            )
        return {"ref": ref, "checkedAt": checked_at, **result}

    semaphore = _asyncio.Semaphore(4)

    async def bounded(ref: str) -> dict[str, object]:
        async with semaphore:
            return await probe(ref)

    results = list(await _asyncio.gather(*(bounded(ref) for ref in refs)))
    return JSONResponse({"items": results, "checkedAt": utc_now()})



class SubscriptionMigrate(BaseModel):
    """POST /api/v1/subscriptions/{ref}/migrate body (F044)."""

    model_config = {"extra": "forbid"}

    newUrl: str = Field(min_length=1)


@router.post("/api/v1/subscriptions/{subscription_ref}/migrate")
async def migrate_subscription(
    subscription_ref: str, payload: SubscriptionMigrate, request: Request
) -> Response:
    """F044 RSS 地址迁移（能力内路径，诚实文案）。

    FreshRSS (greader) 没有"原位改 feed URL"端点——迁移 = 校验新地址
    → 新建订阅 → Lumi 备注/覆盖/静音设置随迁 → 旧订阅打 replaced_by
    标记（不删除、已读/收藏不动，用户确认后可自行退订旧源）。

    校验失败（422）与同 URL（409）不产生任何变更。"""
    from fastapi.responses import JSONResponse

    from lumirss.deps import _get_preview_service
    from lumirss.source_notes import SourceNotesStore
    from lumirss.source_overrides import SourceOverrideStore

    try:
        old_stream_id = decode_subscription_ref(subscription_ref)
    except InvalidSubscriptionReference:
        return JSONResponse(
            status_code=400,
            content={"error": {"type": "invalid_subscription_ref", "message": "订阅引用无效。"}},
        )
    control = _get_control_adapter(request)
    subscription = next(
        (sub for sub in await control.list_subscriptions() if sub.stream_id == old_stream_id),
        None,
    )
    if subscription is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "subscription_not_found", "message": "订阅不存在。"}},
        )
    new_url = payload.newUrl.strip()
    if new_url == subscription.feed_url:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "migration_same_url",
                    "message": "新地址与当前地址相同。",
                }
            },
        )
    # 步骤 1：feed-preview 校验（可达 + 是有效 feed）。失败 → 422，零变更。
    try:
        preview = await _get_preview_service(request).preview(new_url)
    except Exception as exc:  # noqa: BLE001 — 校验失败是正常分支
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "migration_invalid_url",
                    "message": f"新地址不可用（无法访问或不是有效 feed）：{exc}",
                }
            },
        )
    # 步骤 3：新建订阅（FreshRSS 侧唯一能力内路径；服务端确认后返回）。
    title = subscription.title or preview.title or None
    try:
        new_subscription = await control.subscribe(new_url, title=title)
    except Exception as exc:  # noqa: BLE001 — 上游失败如实上报，零变更
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "migration_subscribe_failed",
                    "message": f"新订阅创建失败：{exc}",
                }
            },
        )
    new_ref = new_subscription.subscription_ref
    db = request.app.state.db
    # Lumi 元数据随迁：备注（新旧均保留）+ 显示覆盖（hidden/show/stale）。
    copied_notes = False
    copied_overrides = False
    old_notes = await SourceNotesStore(db).get_notes(subscription_ref)
    if any(old_notes.get(field) for field in ("note", "reason", "maintenance_log")) and new_ref:
        await SourceNotesStore(db).update_notes(
            new_ref,
            note=old_notes.get("note"),
            reason=old_notes.get("reason"),
            maintenance_log=old_notes.get("maintenance_log"),
        )
        copied_notes = True
    override_store = SourceOverrideStore(db)
    old_override = await override_store.get_override(subscription.feed_url)
    if old_override is not None and (
        old_override.get("hiddenUntil")
        or old_override.get("showFrom")
        or old_override.get("staleAlertHours")
    ):
        _UNSET = object()
        await override_store.set_fields(
            new_url,
            hidden_until=old_override["hiddenUntil"] if old_override.get("hiddenUntil") else None,
            show_from=old_override["showFrom"] if old_override.get("showFrom") else None,
            stale_alert_hours=(
                old_override["staleAlertHours"] if old_override.get("staleAlertHours") else None
            ),
        )
        copied_overrides = True
    # replaced_by 标记（旧订阅保留不删）。
    await db.execute(
        "INSERT INTO source_migrations (old_feed_url, old_subscription_ref, new_feed_url, new_subscription_ref, migrated_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(old_feed_url) DO UPDATE SET new_feed_url = excluded.new_feed_url, new_subscription_ref = excluded.new_subscription_ref, migrated_at = excluded.migrated_at",
        (
            subscription.feed_url,
            subscription_ref,
            new_url,
            new_ref,
            utc_now(),
        ),
    )
    return JSONResponse(
        status_code=200,
        content={
            "oldSubscriptionRef": subscription_ref,
            "oldFeedUrl": subscription.feed_url,
            "newSubscriptionRef": new_ref,
            "newFeedUrl": new_url,
            "newTitle": preview.title,
            "copiedNotes": copied_notes,
            "copiedOverrides": copied_overrides,
            "note": "旧订阅已保留（已读/收藏不动）；确认新源正常后可自行退订旧源。",
        },
    )


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

    0067：读当前用户绑定的 public_url（激活/迁移时写入），env 配置只在
    owner 迁移时授予 owner。内部 FRESHRSS_BASE_URL（可能是 Docker 主机
    名或回环地址）永不暴露给浏览器，URL 不携带凭据。
    """
    try:
        await request.app.state.db.migrate()
        row = await request.app.state.db.fetch_one("SELECT public_url FROM freshrss_binding WHERE id = 1")
    except Exception:  # noqa: BLE001 — 未绑定诚实返回 null
        return {"url": None}
    url = str(row["public_url"]) if row and row["public_url"] else None
    return {"url": url or None}


@router.get(
    "/api/v1/freshrss/native-url",
    response_model=FreshRssNativeUrl,
)
async def freshrss_native_url(request: Request) -> Response:
    """P09 委托入口：本账户 FreshRSS 原生界面的可直达坐标。

    返回**恰好** ``{origin, username}``：origin 是绑定里浏览器可达的
    public_url（内部 FRESHRSS_BASE_URL 永不回显——它可能是浏览器无法
    且不应到达的 Docker 主机名，与 /api/v1/freshrss-ui 同一安全决策），
    username 是该账户在 FreshRSS 侧的登录名（让原生界面里的身份可
    识别）。密码与 greader token 不在模型里，契约上无凭据可泄。

    绑定未完成或未配置浏览器可达地址 → 409 ``freshrss_native_url_unavailable``
    （诚实的"暂不可用"状态，UI 显示待定文案、绝不渲染假链接）。
    身份由会话/内部令牌中间件统一强制（/api/* 全量门禁）。
    """
    from fastapi.responses import JSONResponse

    try:
        await request.app.state.db.migrate()
        row = await request.app.state.db.fetch_one(
            "SELECT public_url, username FROM freshrss_binding WHERE id = 1"
        )
    except Exception:  # noqa: BLE001 — 数据库异常与未绑定同等诚实处理
        row = None
    origin = str(row["public_url"] or "").rstrip("/") if row else ""
    username = str(row["username"] or "") if row else ""
    if not origin or not username:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "freshrss_native_url_unavailable",
                    "message": "FreshRSS 绑定尚未完成或未配置浏览器可达地址，原生界面入口暂不可用。",
                }
            },
        )
    return JSONResponse(content={"origin": origin, "username": username})


async def _probe_feed_url(
    feed_url: str, timeout_s: float, *, http_client=None
) -> dict[str, object]:
    """单源探测：HEAD → 降级 GET → 有界读前 4KB 判定。

    ``http_client`` 可注入（测试用 httpx.MockTransport，绝不打真实网络）。"""
    import contextlib
    import urllib.parse

    import httpx

    parts = urllib.parse.urlsplit(feed_url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return {"status": "network_error"}
    client = http_client or httpx.AsyncClient(trust_env=False)
    try:
        try:
            response = await client.head(feed_url, timeout=timeout_s, follow_redirects=False)
            if response.status_code in (405, 501):
                response = await client.get(feed_url, timeout=timeout_s, follow_redirects=False)
        except httpx.UnsupportedProtocol:
            return {"status": "network_error"}
        if response.status_code in (401, 403):
            return {"status": "auth_error", "httpStatus": response.status_code}
        if response.status_code in (404, 410):
            return {"status": "not_found", "httpStatus": response.status_code}
        if response.status_code == 429:
            return {"status": "rate_limited", "httpStatus": response.status_code}
        if response.status_code >= 400:
            return {"status": "network_error", "httpStatus": response.status_code}
        content_type = response.headers.get("content-type", "").lower()
        if any(marker in content_type for marker in ("xml", "rss", "atom")):
            return {"status": "ok", "httpStatus": response.status_code}
        body_head = b""
        with contextlib.suppress(Exception):
            raw = await client.get(feed_url, timeout=timeout_s, follow_redirects=False)
            body_head = raw.content[:4096]
        if b"<rss" in body_head or b"<feed" in body_head:
            return {"status": "ok", "httpStatus": response.status_code}
        return {"status": "bad_content", "httpStatus": response.status_code}
    except httpx.TimeoutException:
        return {"status": "timeout"}
    except httpx.HTTPError:
        return {"status": "network_error"}


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


