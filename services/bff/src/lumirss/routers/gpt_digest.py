"""GPT 日报 routes（M4）。

- 设置读写：/api/v1/gpt-digest/settings（会话认证，标准 /api/v1 面）；
- 显式生成：POST /api/v1/gpt-digest/generate —— 用户动作，忽略
  ``enabled``（与 mail digest send-now 同一契约）；生成是异步的意图上
  仍同步等待结果，失败映射为稳定错误（no_material / generation_failed /
  ai_not_configured）；
- 期刊列表/详情：/api/v1/gpt-digest/issues（列表不带正文）；
- 订阅：GET /feeds/gpt-digest/{token}.atom —— token 即凭据（持有即
  访问）：常量时间比较、绝不记日志、可轮换；GET 永不触发生成、不抓
  上游、不收费；ETag/304 稳定（同内容字节级一致，见 atom_render 约定）。
"""

import hashlib

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from lumirss.ai_profiles import PurposeAiSettings
from lumirss.api_sources import atom_base
from lumirss.atom_render import AtomEntry, render_feed
from lumirss.gpt_digest import (
    DigestMaterialEmpty,
    DigestOutputInvalid,
    generate_issue,
)
from lumirss.gpt_digest_issues import GptDigestIssuesStore
from lumirss.gpt_digest_store import GptDigestStore
from lumirss.models import (
    GptDigestFeedInfo,
    GptDigestIssueList,
    GptDigestSettings,
    GptDigestSettingsUpdate,
)
from lumirss.util import constant_time_equals

from ..deps import _get_ai_profile_store, _get_ai_settings_store

router = APIRouter()

_MAX_FEED_ITEMS = 30  # 订阅输出的历史上限（期号倒序）


def _store(request: Request) -> GptDigestStore:
    return GptDigestStore(request.app.state.db, request.app.state.secrets_store)


def _issues(request: Request) -> GptDigestIssuesStore:
    return GptDigestIssuesStore(request.app.state.db, _store(request))


def _settings_model(settings: dict) -> GptDigestSettings:
    return GptDigestSettings(
        enabled=settings["enabled"],
        hour=settings["hour"],
        timezone=settings["timezone"],
        windowHours=settings["windowHours"],
        limitCount=settings["limitCount"],
        lastIssueKey=settings["lastIssueKey"],
        lastError=settings["lastError"],
    )


@router.get("/api/v1/gpt-digest/settings", response_model=GptDigestSettings)
async def get_gpt_digest_settings(request: Request) -> GptDigestSettings:
    return _settings_model(await _store(request).load())


@router.put("/api/v1/gpt-digest/settings", response_model=GptDigestSettings)
async def update_gpt_digest_settings(
    payload: GptDigestSettingsUpdate, request: Request
) -> GptDigestSettings:
    store = _store(request)
    settings = await store.save(payload.model_dump(exclude_none=True))
    return _settings_model(settings)


@router.get("/api/v1/gpt-digest/feed", response_model=GptDigestFeedInfo)
async def get_gpt_digest_feed(request: Request) -> GptDigestFeedInfo:
    """订阅路径（含 token）。token 是密码级秘密：只在会话认证的 UI 里
    返回，绝不进公开文档、日志或共享缓存。"""
    store = _store(request)
    token = store.ensure_feed_token()
    return GptDigestFeedInfo(atomPath=f"/feeds/gpt-digest/{token}.atom")


@router.post("/api/v1/gpt-digest/feed/rotate", response_model=GptDigestFeedInfo)
async def rotate_gpt_digest_feed(request: Request) -> GptDigestFeedInfo:
    token = _store(request).rotate_feed_token()
    return GptDigestFeedInfo(atomPath=f"/feeds/gpt-digest/{token}.atom")


@router.post("/api/v1/gpt-digest/generate")
async def generate_gpt_digest(request: Request) -> Response:
    """显式生成/修订当天期号。启用与否不影响（显式用户动作）。"""
    store = _store(request)
    issues = _issues(request)
    settings = await store.load()
    adapter = request.app.state.freshrss_adapter
    if adapter is None:
        return JSONResponse(
            status_code=503,
            content={
                "error": {"type": "freshrss_unconfigured", "message": "FreshRSS 未配置。"}
            },
        )
    from lumirss.ai_provider import OpenAICompatibleProvider

    ai_settings = PurposeAiSettings(
        _get_ai_settings_store(request),
        _get_ai_profile_store(request),
        "summary",
    )

    async def provider_factory(base_url: str, model: str):
        effective = await _get_ai_profile_store(request).effective_config(
            "summary", await _get_ai_settings_store(request).load(), ""
        )
        return OpenAICompatibleProvider(
            request.app.state.http_client,
            base_url=effective.base_url or base_url,
            model=effective.model or model,
            api_key=effective.api_key or "",
        )

    try:
        row = await generate_issue(
            store,
            issues,
            adapter=adapter,
            ai_settings=ai_settings,
            provider_factory=provider_factory,
            settings=settings,
        )
    except DigestMaterialEmpty as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "no_material", "message": str(exc)}},
        )
    except DigestOutputInvalid as exc:
        return JSONResponse(
            status_code=502,
            content={
                "error": {"type": "generation_failed", "message": str(exc)}
            },
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
    dto = issues.issue_to_dto(row)
    return JSONResponse(
        status_code=200,
        content={"issue": dto, "promptVersion": "gpt-digest-v1"},
    )


@router.get("/api/v1/gpt-digest/issues", response_model=GptDigestIssueList)
async def list_gpt_digest_issues(
    request: Request, limit: int = 14
) -> GptDigestIssueList:
    rows = await _issues(request).recent_issues(limit)
    return GptDigestIssueList(
        items=[_issues(request).issue_to_dto(row) for row in rows]
    )


@router.get("/feeds/gpt-digest/{token}.atom")
async def serve_gpt_digest_atom(token: str, request: Request) -> Response:
    """只读订阅输出。token 错误 → 404（不区分「无此资源」与「token 错」）。"""
    store = _store(request)
    expected = store.feed_token()
    if not expected or not constant_time_equals(token, expected):
        return Response(status_code=404)
    rows = await _issues(request).recent_issues(_MAX_FEED_ITEMS)
    entries = [
        AtomEntry(
            entry_id=f"urn:lumirss:gptdigest:{row['issue_key']}",
            title=str(row["title"]),
            updated=str(row["updated_at"]),
            published=str(row["published_at"]),
            content_html=str(row["body_html"]),
        )
        for row in rows
    ]
    updated = max(
        (str(row["updated_at"]) for row in rows), default=store.now_utc()
    )
    atom = render_feed(
        feed_id="urn:lumirss:gptdigest",
        title="LumiRSS GPT 日报",
        updated=updated,
        self_href=atom_base() + f"/feeds/gpt-digest/{token}.atom",
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
