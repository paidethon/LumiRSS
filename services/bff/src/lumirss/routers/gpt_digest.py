"""GPT 日报 routes（M4 + F01 多配置）。

- 配置 CRUD：/api/v1/gpt-digest/configs（新增/编辑/暂停/删除；删除
  级联其期刊；配置 1「默认日报」不可删除）。旧单配置端点
  /api/v1/gpt-digest/settings|preview|generate|issues 继续可用，等价
  于配置 1。
- 来源白名单：feedUrlAllow（子串规则）决定该配置可见的订阅——不同
  配置材料互不串用。
- 订阅：GET /feeds/gpt-digest/{token}.atom（默认配置）与
  /feeds/gpt-digest/{config_id}.{token}.atom（指定配置）。token 即凭据：
  常量时间比较、绝不记日志、可轮换；GET 永不触发生成、不抓上游、
  不收费；ETag/304 稳定。
- 生成失败映射为稳定错误（no_material / generation_failed /
  ai_not_configured / ai_upstream）；空窗口不生成空日报，保留上一份
  有效发布物。
"""

import hashlib
import json
from datetime import UTC

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from lumirss.api_sources import atom_base
from lumirss.atom_render import AtomEntry, render_feed
from lumirss.gpt_digest import (
    DigestMaterialEmpty,
    DigestOutputInvalid,
    build_preview,
    generate_issue,
)
from lumirss.gpt_digest_configs import GptDigestConfigStore
from lumirss.gpt_digest_issues import GptDigestIssuesStore
from lumirss.gpt_digest_store import GptDigestStore
from lumirss.models import (
    GptDigestConfig,
    GptDigestConfigList,
    GptDigestConfigUpdate,
    GptDigestCreate,
    GptDigestFeedInfo,
    GptDigestIssueList,
    GptDigestIssueRevise,
    GptDigestPreview,
    GptDigestSettings,
    GptDigestSettingsUpdate,
)
from lumirss.util import constant_time_equals

router = APIRouter()

_MAX_FEED_ITEMS = 30  # 订阅输出的历史上限（期号倒序）


def _config_store(request: Request) -> GptDigestConfigStore:
    return GptDigestConfigStore(request.app.state.db)


def _issues(request: Request) -> GptDigestIssuesStore:
    return GptDigestIssuesStore(request.app.state.db)


def _store(request: Request) -> GptDigestStore:
    return GptDigestStore(request.app.state.db, request.app.state.secrets_store)


def _settings_model(config: dict) -> GptDigestSettings:
    return GptDigestSettings(
        enabled=config["enabled"],
        hour=config["hour"],
        timezone=config["timezone"],
        windowHours=config["windowHours"],
        limitCount=config["limitCount"],
        perSourceCap=config["perSourceCap"],
        lastIssueKey=config["lastIssueKey"],
        lastError=config["lastError"],
    )


# -- 配置 CRUD（F01） --------------------------------------------------------


@router.get("/api/v1/gpt-digest/configs", response_model=GptDigestConfigList)
async def list_gpt_digest_configs(request: Request) -> GptDigestConfigList:
    items = await _config_store(request).list_configs()
    return GptDigestConfigList(items=[GptDigestConfig(**item) for item in items])


@router.post("/api/v1/gpt-digest/configs", response_model=GptDigestConfig, status_code=201)
async def create_gpt_digest_config(
    payload: GptDigestCreate, request: Request
) -> GptDigestConfig:
    config = await _config_store(request).create_config(payload.model_dump(exclude_none=True))
    return GptDigestConfig(**config)


@router.put("/api/v1/gpt-digest/configs/{config_id}", response_model=GptDigestConfig)
async def update_gpt_digest_config(
    config_id: int, payload: GptDigestConfigUpdate, request: Request
) -> GptDigestConfig:
    config = await _config_store(request).update_config(
        config_id, payload.model_dump(exclude_none=True)
    )
    if config is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "not_found", "message": "配置不存在。"}},
        )
    return GptDigestConfig(**config)


@router.delete("/api/v1/gpt-digest/configs/{config_id}", status_code=204)
async def delete_gpt_digest_config(config_id: int, request: Request) -> Response:
    deleted = await _config_store(request).delete_config(config_id)
    if not deleted:
        return JSONResponse(
            status_code=(400 if config_id <= 1 else 404),
            content={
                "error": {
                    "type": "undeletable" if config_id <= 1 else "not_found",
                    "message": "默认配置不可删除。" if config_id <= 1 else "配置不存在。",
                }
            },
        )
    return Response(status_code=204)


@router.get("/api/v1/gpt-digest/configs/{config_id}/feed", response_model=GptDigestFeedInfo)
async def get_config_feed(config_id: int, request: Request) -> GptDigestFeedInfo:
    config = await _config_store(request).get_config(config_id)
    if config is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "not_found", "message": "配置不存在。"}},
        )
    token = _store(request).ensure_feed_token()
    return GptDigestFeedInfo(atomPath=f"/feeds/gpt-digest/{config_id}.{token}.atom")


@router.get(
    "/api/v1/gpt-digest/configs/{config_id}/preview", response_model=GptDigestPreview
)
async def preview_config_digest(config_id: int, request: Request) -> GptDigestPreview:
    config = await _config_store(request).get_config(config_id)
    if config is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "not_found", "message": "配置不存在。"}},
        )
    adapter = request.app.state.freshrss_adapter
    if adapter is None:
        return JSONResponse(
            status_code=503,
            content={
                "error": {"type": "freshrss_unconfigured", "message": "FreshRSS 未配置。"}
            },
        )
    preview = await build_preview(adapter, config, request.app.state.db)
    return GptDigestPreview(**preview)


@router.post("/api/v1/gpt-digest/configs/{config_id}/generate")
async def generate_config_digest(config_id: int, request: Request) -> Response:
    return await _generate_for_config(request, await _config_store(request).get_config(config_id))


@router.get(
    "/api/v1/gpt-digest/configs/{config_id}/issues", response_model=GptDigestIssueList
)
async def list_config_issues(
    config_id: int, request: Request, limit: int = 14
) -> GptDigestIssueList:
    rows = await _issues(request).recent_issues(config_id, limit)
    return GptDigestIssueList(items=[_issues(request).issue_to_dto(row) for row in rows])


# -- 旧单配置端点（= 配置 1 兼容面） -----------------------------------------


@router.get("/api/v1/gpt-digest/settings", response_model=GptDigestSettings)
async def get_gpt_digest_settings(request: Request) -> GptDigestSettings:
    config = await _config_store(request).get_config(1)
    if config is None:
        return GptDigestSettings(enabled=False, hour=8)
    return _settings_model(config)


@router.put("/api/v1/gpt-digest/settings", response_model=GptDigestSettings)
async def update_gpt_digest_settings(
    payload: GptDigestSettingsUpdate, request: Request
) -> GptDigestSettings:
    config = await _config_store(request).update_config(
        1, payload.model_dump(exclude_none=True)
    )
    assert config is not None  # 配置 1 恒存在（迁移保证）
    return _settings_model(config)


@router.get("/api/v1/gpt-digest/feed", response_model=GptDigestFeedInfo)
async def get_gpt_digest_feed(request: Request) -> GptDigestFeedInfo:
    """订阅路径（含 token）。token 是密码级秘密：只在会话认证的 UI 里
    返回，绝不进公开文档、日志或共享缓存。"""
    token = _store(request).ensure_feed_token()
    return GptDigestFeedInfo(atomPath=f"/feeds/gpt-digest/{token}.atom")


@router.post("/api/v1/gpt-digest/feed/rotate", response_model=GptDigestFeedInfo)
async def rotate_gpt_digest_feed(request: Request) -> GptDigestFeedInfo:
    token = _store(request).rotate_feed_token()
    return GptDigestFeedInfo(atomPath=f"/feeds/gpt-digest/{token}.atom")


@router.get("/api/v1/gpt-digest/preview", response_model=GptDigestPreview)
async def preview_gpt_digest(request: Request) -> GptDigestPreview:
    """F06：生成前看到入选/排除与原因；不调用模型、不写库。"""
    config = await _config_store(request).get_config(1)
    if config is None:
        return JSONResponse(
            status_code=503,
            content={
                "error": {"type": "freshrss_unconfigured", "message": "存储尚未迁移。"}
            },
        )
    adapter = request.app.state.freshrss_adapter
    if adapter is None:
        return JSONResponse(
            status_code=503,
            content={
                "error": {"type": "freshrss_unconfigured", "message": "FreshRSS 未配置。"}
            },
        )
    preview = await build_preview(adapter, config, request.app.state.db)
    return GptDigestPreview(**preview)


@router.post("/api/v1/gpt-digest/generate")
async def generate_gpt_digest(request: Request) -> Response:
    """显式生成/修订当天期号。启用与否不影响（显式用户动作）。"""
    config = await _config_store(request).get_config(1)
    return await _generate_for_config(request, config)


@router.put(
    "/api/v1/gpt-digest/configs/{config_id}/issues/{issue_key}",
    response_model=GptDigestIssueList,
)
async def revise_gpt_digest_issue(
    config_id: int,
    issue_key: str,
    payload: GptDigestIssueRevise,
    request: Request,
) -> Response:
    """F08：人工编辑标题/条目/排序后重新发布同一期。

    修订沿用既有引用（sourceIds 必须存在于生成时的引用集，不可凭空
    新增）；entry id 不变、updated 前移，订阅端不产生新刊次。"""
    issues = _issues(request)
    row = await issues.get_issue(config_id, issue_key)
    if row is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "not_found", "message": "期号不存在。"}},
        )
    try:
        refs = json.loads(str(row["refs_json"] or "{}"))
    except ValueError:
        refs = {}
    from lumirss.gpt_digest import (
        DigestOutputInvalid,
        parse_and_validate_output,
        render_issue_html,
    )

    output = {"title": payload.title, "sections": payload.sections, "limitations": []}
    try:
        validated = parse_and_validate_output(
            json.dumps(output, ensure_ascii=False), list(refs.keys())
        )
    except DigestOutputInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_issue", "message": str(exc)}},
        )
    body_html = render_issue_html(validated, refs)
    updated = await issues.revise_issue(
        config_id=config_id,
        issue_key=issue_key,
        title=validated["title"],
        body_html=body_html,
        sections=validated["sections"],
        note="人工修订",
        updated_at=_utc_now_seconds(),
    )
    if updated is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "not_found", "message": "期号不存在。"}},
        )
    dto = issues.issue_to_dto(updated)
    return JSONResponse(status_code=200, content={"issue": dto})


@router.get("/api/v1/gpt-digest/issues", response_model=GptDigestIssueList)
async def list_gpt_digest_issues(
    request: Request, limit: int = 14
) -> GptDigestIssueList:
    rows = await _issues(request).recent_issues(1, limit)
    return GptDigestIssueList(items=[_issues(request).issue_to_dto(row) for row in rows])


# -- 生成（配置共用） --------------------------------------------------------


async def _generate_for_config(request: Request, config: dict | None) -> Response:
    if config is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "not_found", "message": "配置不存在。"}},
        )
    adapter = request.app.state.freshrss_adapter
    if adapter is None:
        return JSONResponse(
            status_code=503,
            content={
                "error": {"type": "freshrss_unconfigured", "message": "FreshRSS 未配置。"}
            },
        )
    from datetime import datetime

    from lumirss.gpt_digest import _build_ai_deps, plan_run

    ai_settings, provider_factory = _build_ai_deps(request.app.state)
    # F02：显式生成 = 修订「最近一个已过期时点」的期号（不限补刊窗口；
    # 多时点配置的窗口按相邻时点切分）。单时点配置 plan=None 时由
    # generate_issue 走历史语义。
    plan = plan_run(config, datetime.now().astimezone(), catchup_minutes=None)
    try:
        row = await generate_issue(
            _config_store(request),
            _issues(request),
            config=config,
            adapter=adapter,
            ai_settings=ai_settings,
            provider_factory=provider_factory,
            db=request.app.state.db,
            plan=plan,
        )
    except DigestMaterialEmpty as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "no_material", "message": str(exc)}},
        )
    except DigestOutputInvalid as exc:
        return JSONResponse(
            status_code=502,
            content={"error": {"type": "generation_failed", "message": str(exc)}},
        )
    except Exception as exc:  # noqa: BLE001 — typed mapping below
        name = type(exc).__name__
        if name in {"AiNotConfigured", "AiAuthError", "AiModelError"}:
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "type": "ai_not_configured",
                        "message": "AI 未配置或配置不可用（详见设置）。"
                        if name == "AiNotConfigured"
                        else "AI 上游拒绝了本次生成。",
                    }
                },
            )
        if name in {"AiRateLimited", "AiTimeout", "AiUpstreamError"}:
            return JSONResponse(
                status_code=502,
                content={
                    "error": {
                        "type": "ai_upstream",
                        "message": "AI 上游暂时不可用，上一份有效发布物未受影响。",
                    }
                },
            )
        raise
    dto = _issues(request).issue_to_dto(row)
    return JSONResponse(
        status_code=200,
        content={"issue": dto, "promptVersion": "gpt-digest-v1"},
    )


# -- Atom 订阅 ---------------------------------------------------------------


def _parse_feed_spec(spec: str) -> tuple[int, str]:
    """``{token}`` → 配置 1；``{config_id}.{token}`` → 指定配置。"""
    parts = spec.split(".", 1)
    if len(parts) == 2 and parts[0].isdigit():
        return int(parts[0]), parts[1]
    return 1, spec


@router.get("/feeds/gpt-digest/{spec}.atom")
async def serve_gpt_digest_atom(spec: str, request: Request) -> Response:
    """只读订阅输出。token 错误 → 404（不区分「无此资源」与「token 错」）。"""
    config_id, token = _parse_feed_spec(spec)
    expected = _store(request).feed_token()
    if not expected or not constant_time_equals(token, expected):
        return Response(status_code=404)
    config = await _config_store(request).get_config(config_id)
    if config is None:
        return Response(status_code=404)
    rows = await _issues(request).recent_issues(config_id, _MAX_FEED_ITEMS)
    entries = [
        AtomEntry(
            entry_id=f"urn:lumirss:gptdigest:{config_id}:{row['issue_key']}",
            title=str(row["title"]),
            updated=str(row["updated_at"]),
            published=str(row["published_at"]),
            content_html=str(row["body_html"]),
        )
        for row in rows
    ]
    updated = max((str(row["updated_at"]) for row in rows), default=config["createdAt"])
    atom = render_feed(
        feed_id=f"urn:lumirss:gptdigest:{config_id}",
        title=f"LumiRSS GPT 日报 · {config['name']}",
        updated=updated,
        self_href=atom_base() + f"/feeds/gpt-digest/{spec}.atom",
        entries=entries,
        feed_author="LumiRSS",
    )
    etag = f'"{hashlib.sha256(atom.encode("utf-8")).hexdigest()[:32]}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return Response(
        content=atom,
        media_type="application/atom+xml; charset=utf-8",
        headers={"ETag": etag},
    )


__all__ = ["router"]

def _utc_now_seconds() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat(timespec="seconds")
