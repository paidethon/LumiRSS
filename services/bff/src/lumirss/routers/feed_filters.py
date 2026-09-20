"""F045 服务端屏蔽规则路由 —— 规则 CRUD + 试跑。

规则只影响 Lumi entries 时间线视图（GET /api/v1/entries 服务端过滤），
绝不触碰 FreshRSS 的已读/收藏/抓取（负向契约由测试固定）。
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from lumirss.feed_filter_store import (
    FeedFilterRuleStore,
    FilterRuleLimit,
    first_matching_rule,
    validate_rule_payload,
)
from lumirss.models import (
    FeedFilterRule,
    FeedFilterRuleCreate,
    FeedFilterRuleList,
    FeedFilterRuleTrial,
    FeedFilterRuleTrialResult,
)

router = APIRouter()


@router.get("/api/v1/feed-filter-rules", response_model=FeedFilterRuleList)
async def list_rules(request: Request, feedUrl: str | None = None) -> FeedFilterRuleList:
    store = FeedFilterRuleStore(request.app.state.db)
    rules = await store.list_rules(feedUrl)
    return FeedFilterRuleList(items=[FeedFilterRule(**rule) for rule in rules])


@router.post("/api/v1/feed-filter-rules", response_model=FeedFilterRule, status_code=201)
async def create_rule(payload: FeedFilterRuleCreate, request: Request) -> Response:
    field, op, value = validate_rule_payload(
        field=payload.field, op=payload.op, value=payload.value
    )
    store = FeedFilterRuleStore(request.app.state.db)
    try:
        rule = await store.create_rule(
            feed_url=payload.feedUrl.strip(), field=field, op=op, value=value,
            enabled=payload.enabled,
        )
    except FilterRuleLimit as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "filter_rule_limit", "message": str(exc)}},
        )
    return JSONResponse(status_code=201, content=FeedFilterRule(**rule).model_dump())


@router.patch("/api/v1/feed-filter-rules/{rule_id}", response_model=FeedFilterRule)
async def update_rule(rule_id: str, request: Request, enabled: bool | None = None) -> Response:
    store = FeedFilterRuleStore(request.app.state.db)
    rule = await store.update_rule(rule_id, enabled=enabled)
    if rule is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "filter_rule_not_found", "message": "规则不存在。"}},
        )
    return FeedFilterRule(**rule)


@router.delete("/api/v1/feed-filter-rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: str, request: Request) -> Response:
    store = FeedFilterRuleStore(request.app.state.db)
    deleted = await store.delete_rule(rule_id)
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "filter_rule_not_found", "message": "规则不存在。"}},
        )
    return Response(status_code=204)


@router.post(
    "/api/v1/feed-filter-rules/trial",
    response_model=FeedFilterRuleTrialResult,
)
async def trial_rule(payload: FeedFilterRuleTrial, request: Request) -> FeedFilterRuleTrialResult:
    """试跑：对样例标题/作者按当前启用规则求值（首条命中优先）。"""
    store = FeedFilterRuleStore(request.app.state.db)
    rules = await store.list_rules(payload.feedUrl)
    rule = first_matching_rule(
        rules, title=payload.sampleTitle, author=payload.sampleAuthor
    )
    if rule is None:
        return FeedFilterRuleTrialResult(matched=False)
    target = payload.sampleTitle if rule["field"] == "title" else (payload.sampleAuthor or "")
    reason = (
        f"标题{('包含' if rule['op'] == 'contains' else '等于')}「{rule['value']}」"
        if rule["field"] == "title"
        else f"作者{('包含' if rule['op'] == 'contains' else '等于')}「{rule['value']}」"
    )
    _ = target
    return FeedFilterRuleTrialResult(matched=True, ruleId=rule["id"], reason=reason)
