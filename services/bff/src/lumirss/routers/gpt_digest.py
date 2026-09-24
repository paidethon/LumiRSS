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

import contextlib
import hashlib
import json
from datetime import UTC, timedelta
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.api_sources import atom_base
from lumirss.atom_render import AtomEntry, render_feed
from lumirss.gpt_digest import (
    DigestMaterialEmpty,
    DigestOutputInvalid,
    DigestPolishFailed,
    build_preview,
    consume_pool_for_issue,
    generate_issue,
)
from lumirss.gpt_digest_configs import GptDigestConfigStore
from lumirss.gpt_digest_issues import GptDigestIssuesStore, parse_issue_meta
from lumirss.gpt_digest_pool import (
    DigestMaterialPoolStore,
    DigestPoolDuplicate,
)
from lumirss.gpt_digest_store import GptDigestStore, feed_token_impact
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
from lumirss.token_hash import verify_token

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
    # §13.4：仅首次创建返回原始 token（一次性展示）；已存在 → atomPath
    # 为空（UI 显示「已隐藏，可轮换」——明文不可从哈希重建）。
    token = _store(request).ensure_feed_token()
    atom_path_value = (
        f"/feeds/gpt-digest/{config_id}.{token}.atom" if token else ""
    )
    return GptDigestFeedInfo(atomPath=atom_path_value)


@router.get(
    "/api/v1/gpt-digest/configs/{config_id}/preview", response_model=GptDigestPreview
)
async def preview_config_digest(
    config_id: int,
    request: Request,
    put_back: Annotated[list[str] | None, Query(alias="putBack")] = None,
) -> GptDigestPreview:
    """F06/F101：选材预览；``putBack``（可重复参数）为本次显式放回的
    材料身份——与生成请求共用同一选材函数，预览即所得。"""
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
    preview = await build_preview(
        adapter, config, request.app.state.db, put_back=put_back
    )
    return GptDigestPreview(**preview)


@router.get("/api/v1/gpt-digest/configs/{config_id}/missing-dates")
async def missing_digest_dates(
    config_id: int, request: Request, days: int = 30
) -> Response:
    """F032：按配置计划（时区）列出最近 `days` 天内缺失期号的日期。

    已有期号（含草稿）的日期排除；未来日期（今天及以后）不算缺失。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from lumirss.gpt_digest_store import issue_key_for

    config = await _config_store(request).get_config(config_id)
    if config is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "not_found", "message": "配置不存在。"}},
        )
    bounded = max(1, min(days, 90))
    tz = ZoneInfo(config["timezone"]) if config["timezone"] else None
    now = datetime.now(tz) if tz else datetime.now().astimezone()
    existing = set(await _issues(request).all_issue_keys(config_id))
    missing: list[str] = []
    for offset in range(1, bounded + 1):
        day = now.fromtimestamp(now.timestamp(), tz=now.tzinfo) - timedelta(days=offset)
        key = issue_key_for(day, config["timezone"])
        if key not in existing:
            missing.append(key)
    return JSONResponse(
        status_code=200,
        content={"missing": list(reversed(missing)), "existing": sorted(existing)},
    )


class DigestTargetDateBody(BaseModel):
    """POST …/generate 可选体：补刊指定缺失日期 / F101 显式放回列表。

    ``putBack`` 为材料身份（url 或 title: 前缀键，来自预览响应）；
    本次生成显式放回，不影响后续期号的去重。"""

    model_config = {"extra": "forbid"}

    targetDate: str | None = Field(default=None, min_length=8, max_length=10)
    putBack: list[str] | None = Field(default=None, max_length=50)


@router.post("/api/v1/gpt-digest/configs/{config_id}/generate")
async def generate_config_digest(
    config_id: int, request: Request, body: DigestTargetDateBody | None = None
) -> Response:
    target = body.targetDate if body is not None else None
    put_back = body.putBack if body is not None else None
    if target is not None:
        return await _generate_for_missing_date(request, config_id, target, put_back)
    return await _generate_for_config(
        request,
        await _config_store(request).get_config(config_id),
        put_back=put_back,
    )


async def _generate_for_missing_date(
    request: Request,
    config_id: int,
    target: str,
    put_back: list[str] | None = None,
) -> Response:
    """F032：补刊缺失日期。仅允许缺失日期——已有期号（含已发布/草稿）
    的日期 409 protected（不覆盖已发布）；无材料日期报错不产空刊。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from lumirss.gpt_digest import DigestMaterialEmpty

    config = await _config_store(request).get_config(config_id)
    if config is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "not_found", "message": "配置不存在。"}},
        )
    existing = set(await _issues(request).all_issue_keys(config_id))
    if target in existing:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "protected",
                    "message": f"{target} 已有期号，不可覆盖（如需修订请用编辑）。",
                }
            },
        )
    # 缺失日期校验：不得是未来日期
    tz = ZoneInfo(config["timezone"]) if config["timezone"] else None
    try:
        y, m, d = (int(part) for part in target.split("-"))
    except ValueError:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_request", "message": "targetDate 需为 YYYY-MM-DD。"}},
        )
    now_local = datetime.now(tz) if tz else datetime.now().astimezone()
    target_end = datetime(y, m, d, 23, 59, 59, tzinfo=now_local.tzinfo)
    if target_end > now_local:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_request", "message": "不能补刊未来日期。"}},
        )
    adapter = request.app.state.freshrss_adapter
    if adapter is None:
        return JSONResponse(
            status_code=503,
            content={
                "error": {"type": "freshrss_unconfigured", "message": "FreshRSS 未配置。"}
            },
        )
    from lumirss.gpt_digest import _build_ai_deps

    ai_settings, provider_factory = _build_ai_deps(request.app.state)
    try:
        row = await generate_issue(
            _config_store(request),
            _issues(request),
            config=config,
            adapter=adapter,
            ai_settings=ai_settings,
            provider_factory=provider_factory,
            db=request.app.state.db,
            now=target_end,
            draft=True,
            put_back=put_back,
        )
    except DigestMaterialEmpty as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "no_material", "message": str(exc)}},
        )
    except Exception as exc:  # noqa: BLE001 — typed mapping below
        name = type(exc).__name__
        if name in {"AiNotConfigured", "AiAuthError", "AiModelError"}:
            return JSONResponse(
                status_code=409,
                content={"error": {"type": "ai_not_configured", "message": "AI 未配置或配置不可用。"}},
            )
        if name in {"AiRateLimited", "AiTimeout", "AiUpstreamError"}:
            return JSONResponse(
                status_code=502,
                content={"error": {"type": "ai_upstream", "message": "AI 上游暂时不可用。"}},
            )
        raise
    dto = _issues(request).issue_to_dto(row)
    return JSONResponse(status_code=200, content={"issue": dto})


@router.get(
    "/api/v1/gpt-digest/configs/{config_id}/issues", response_model=GptDigestIssueList
)
async def list_config_issues(
    config_id: int, request: Request, limit: int = 14
) -> GptDigestIssueList:
    rows = await _issues(request).recent_issues(config_id, limit, include_drafts=True)
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
    # §13.4：同上——一次性展示；再查看为空。
    token = _store(request).ensure_feed_token()
    atom_path_value = f"/feeds/gpt-digest/{token}.atom" if token else ""
    return GptDigestFeedInfo(atomPath=atom_path_value)


@router.post("/api/v1/gpt-digest/feed/rotate")
async def rotate_gpt_digest_feed(request: Request, dryRun: bool = False) -> Response:
    """F103：轮换订阅 token。``dryRun=true`` → 影响预览（零变更：
    token、secrets、时刻戳都不动）；省略/false → 执行轮换（现有语义：
    旧链接立即失效）。"""
    store = _store(request)
    if dryRun:
        impact = await feed_token_impact(request.app.state.secrets_store, request.app.state.db)
        return JSONResponse(
            status_code=200,
            content={"dryRun": True, "impact": impact},
        )
    token = store.rotate_feed_token()
    return JSONResponse(
        status_code=200,
        content={"atomPath": f"/feeds/gpt-digest/{token}.atom"},
    )


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
    """F08 + N173：人工修订同一期后重新发布。

    - F08 全量：提交 title+sections（sourceIds 必须存在于生成时的引用
      集，不可凭空新增）；entry id 不变、updated 前移。
    - N173 逐句：``sentenceOps``（revise 改写 / delete 删除）直接作用
      在当前内容上（省略 title/sections 时）；改写后的句子匹配不到生
      成时引用 → 映射重算为待核实——绝不凭空延续引用。
    两种路径都会重算句子映射并重渲染 body_html（Atom 订阅同步）。"""
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

    stored_sections = _stored_sections_list(row)
    if payload.sentenceOps:
        if payload.sections is not None:
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "type": "invalid_request",
                        "message": "sentenceOps 与全量 sections 不可同时提交。",
                    }
                },
            )
        sections = json.loads(json.dumps(stored_sections, ensure_ascii=False))  # 深拷贝
        error = _apply_sentence_ops(sections, payload.sentenceOps)
        if error is not None:
            return JSONResponse(
                status_code=422,
                content={"error": {"type": "invalid_request", "message": error}},
            )
        title = payload.title if payload.title is not None else str(row["title"])
    else:
        if payload.sections is None:
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "type": "invalid_request",
                        "message": "需要 sections 或 sentenceOps。",
                    }
                },
            )
        sections = payload.sections
        title = payload.title if payload.title is not None else str(row["title"])

    from lumirss.gpt_digest import (
        DigestOutputInvalid,
        parse_and_validate_output,
        render_issue_html,
    )
    from lumirss.gpt_digest_issues import build_sentence_map, recompute_sentence_map

    output = {"title": title, "sections": sections, "limitations": []}
    try:
        validated = parse_and_validate_output(
            json.dumps(output, ensure_ascii=False), list(refs.keys())
        )
    except DigestOutputInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_issue", "message": str(exc)}},
        )
    # N173：映射重算——以修订前映射（meta 里存有；旧期号从现内容推导）
    # 按句子原文匹配：改写/新增 → 待核实；删除 → 消失。
    meta = parse_issue_meta(dict(row))
    old_map = meta.get("sentenceMap")
    if not isinstance(old_map, list):
        old_map = build_sentence_map(stored_sections)
    meta["sentenceMap"] = recompute_sentence_map(old_map, validated["sections"])
    body_html = render_issue_html(validated, refs)
    updated = await issues.revise_issue(
        config_id=config_id,
        issue_key=issue_key,
        title=validated["title"],
        body_html=body_html,
        sections=validated["sections"],
        note="人工修订",
        updated_at=_utc_now_seconds(),
        meta_json=json.dumps(meta, ensure_ascii=False),
    )
    if updated is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "not_found", "message": "期号不存在。"}},
        )
    dto = issues.issue_to_dto(updated)
    return JSONResponse(status_code=200, content={"issue": dto})


def _stored_sections_list(row: dict) -> list[dict]:
    """期号行 → sections 列表（兼容 dict 存态与 list 存态）。"""
    try:
        stored = json.loads(str(row["sections_json"] or "[]"))
    except ValueError:
        return []
    if isinstance(stored, dict):
        stored = stored.get("sections") or []
    return [s for s in stored if isinstance(s, dict)]


def _apply_sentence_ops(
    sections: list[dict], ops: list
) -> str | None:
    """N173：在 sections 上原位应用逐句操作；非法 → 错误文案（422）。

    句子切分保真（``"".join == 原文``），修订文本直接替换目标句，删除
    整句移除；操作后重渲染与映射重算由调用方完成。"""
    from lumirss.gpt_digest_issues import split_sentences

    if len(ops) > 100:
        return "sentenceOps 数量超限（≤100）。"
    for op in ops:
        try:
            section = sections[op.sectionIndex]
            item = section["items"][op.itemIndex]
        except (IndexError, KeyError, TypeError):
            return "sentenceOps 索引越界。"
        summary = str(item.get("summary") or "")
        sentences = split_sentences(summary)
        if op.sentenceIndex >= len(sentences):
            return "sentenceOps 句子索引越界。"
        if op.op == "delete":
            del sentences[op.sentenceIndex]
        elif op.op == "revise":
            text = (op.text or "").strip()
            if not text:
                return "revise 操作需要非空 text。"
            sentences[op.sentenceIndex] = text
        else:  # pragma: no cover — pydantic Literal 已限定
            return "未知的 sentenceOps 操作。"
        item["summary"] = "".join(sentences)
    return None


@router.post("/api/v1/gpt-digest/configs/{config_id}/issues/{issue_key}/publish")
async def publish_gpt_digest_issue(
    config_id: int, issue_key: str, request: Request
) -> Response:
    """F031：草稿审阅后显式发布（幂等：已 published 再发布 200 不变）。

    发布前复用既有引用校验（sections 中的 sourceId 必须存在于生成时的
    引用集）：校验失败保留 draft 并报 422，绝不半发布。"""
    issues = _issues(request)
    row = await issues.get_issue(config_id, issue_key)
    if row is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "not_found", "message": "期号不存在。"}},
        )
    if row["status"] != "published":
        try:
            refs = json.loads(str(row["refs_json"] or "{}"))
        except ValueError:
            refs = {}
        try:
            from lumirss.gpt_digest import parse_and_validate_output

            parse_and_validate_output(
                str(row["sections_json"] or "{}"), list(refs.keys())
            )
        except DigestOutputInvalid as exc:
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "type": "invalid_issue",
                        "message": f"引用校验失败，仍是草稿：{exc}",
                    }
                },
            )
    published = await issues.publish_issue(config_id, issue_key)
    assert published is not None
    # F102：审阅发布草稿 → 该期引用命中的素材池条目标记已用（尽力而为）。
    adapter = request.app.state.freshrss_adapter
    if adapter is not None and request.app.state.db is not None:
        with contextlib.suppress(Exception):
            await consume_pool_for_issue(
                adapter,
                DigestMaterialPoolStore(request.app.state.db),
                config_id,
                published,
            )
    dto = issues.issue_to_dto(published)
    return JSONResponse(status_code=200, content={"issue": dto})


@router.post("/api/v1/gpt-digest/configs/{config_id}/issues/{issue_key}/explain")
async def explain_gpt_digest_issue(
    config_id: int, issue_key: str, request: Request
) -> Response:
    """F05：为某期生成初学者解释版（独立条目 key = {key}-x）。

    输入只含该期自身的总结与来源标题——不可能引入原文之外的新事实。
    AI 未配置/上游失败映射为稳定错误；原版不受影响。"""
    from lumirss.gpt_digest import (
        DigestOutputInvalid,
        _build_ai_deps,
        explain_issue,
    )

    config = await _config_store(request).get_config(config_id)
    if config is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "not_found", "message": "配置不存在。"}},
        )
    ai_settings, provider_factory = _build_ai_deps(request.app.state)
    try:
        row = await explain_issue(
            _config_store(request),
            _issues(request),
            config=config,
            ai_settings=ai_settings,
            provider_factory=provider_factory,
            issue_key=issue_key,
        )
    except DigestOutputInvalid as exc:
        return JSONResponse(
            status_code=502,
            content={"error": {"type": "generation_failed", "message": str(exc)}},
        )
    except Exception as exc:  # noqa: BLE001 — typed mapping
        if type(exc).__name__ in {"AiNotConfigured", "AiAuthError", "AiModelError"}:
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "type": "ai_not_configured",
                        "message": "AI 未配置或配置不可用（详见设置）。",
                    }
                },
            )
        if type(exc).__name__ in {"AiRateLimited", "AiTimeout", "AiUpstreamError"}:
            return JSONResponse(
                status_code=502,
                content={
                    "error": {
                        "type": "ai_upstream",
                        "message": "AI 上游暂时不可用，原版未受影响。",
                    }
                },
            )
        raise
    dto = _issues(request).issue_to_dto(row)
    return JSONResponse(status_code=200, content={"issue": dto})


@router.post("/api/v1/gpt-digest/configs/{config_id}/issues/{issue_key}/retry-polish")
async def retry_polish_gpt_digest_issue(
    config_id: int, issue_key: str, request: Request
) -> Response:
    """N172：仅重跑润色阶段（选材/总结成果保留不动）。

    语义：同 issue_key 修订（entry id 不变、updated 前移、状态不变）；
    成功清除 meta.polishFailed。失败 502 polish_failed，期号保持原样。"""
    from lumirss.gpt_digest import (
        DigestMaterialEmpty,
        _build_ai_deps,
        retry_polish_issue,
    )

    config = await _config_store(request).get_config(config_id)
    if config is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "not_found", "message": "配置不存在。"}},
        )
    ai_settings, provider_factory = _build_ai_deps(request.app.state)
    try:
        row = await retry_polish_issue(
            _issues(request),
            _config_store(request),
            config_id=config_id,
            issue_key=issue_key,
            config=config,
            ai_settings=ai_settings,
            provider_factory=provider_factory,
        )
    except DigestMaterialEmpty as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "no_material", "message": str(exc)}},
        )
    except Exception as exc:  # noqa: BLE001 — typed mapping below
        name = type(exc).__name__
        if name in {"AiNotConfigured", "AiAuthError", "AiModelError"}:
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "type": "ai_not_configured",
                        "message": "AI 未配置或配置不可用（详见设置）。",
                    }
                },
            )
        if name in {"AiRateLimited", "AiTimeout", "AiUpstreamError", "AiInvalidResponse"}:
            return JSONResponse(
                status_code=502,
                content={"error": {"type": "ai_upstream", "message": str(exc)}},
            )
        raise
    dto = _issues(request).issue_to_dto(row)
    return JSONResponse(status_code=200, content={"issue": dto})


@router.post("/api/v1/gpt-digest/configs/{config_id}/weekly")
async def generate_weekly_digest(config_id: int, request: Request) -> Response:
    """F03：周报——聚合该配置最近 7 天日刊（≤7 期）为一周回顾。

    期号 = 配置时区 ISO 周（2026-W38）；输入只含已发布日刊总结与引用
    （来源可追溯）；空输入 422 no_material。"""
    from lumirss.gpt_digest import (
        DigestMaterialEmpty,
        DigestOutputInvalid,
        generate_weekly,
    )

    config = await _config_store(request).get_config(config_id)
    if config is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "not_found", "message": "配置不存在。"}},
        )
    # 周报只读已发布日刊——不需要 FreshRSS 适配器（与日刊生成不同）。
    from lumirss.gpt_digest import _build_ai_deps

    ai_settings, provider_factory = _build_ai_deps(request.app.state)
    try:
        row = await generate_weekly(
            _config_store(request),
            _issues(request),
            config=config,
            ai_settings=ai_settings,
            provider_factory=provider_factory,
        )
    except DigestMaterialEmpty as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "no_material", "message": str(exc)}},
        )
    except DigestPolishFailed as exc:
        # N172：润色失败——选材/总结草稿已保留（响应携带该草稿），错误
        # 诚实带阶段名；可经 retry-polish 仅补润色。
        draft_dto = _issues(request).issue_to_dto(exc.row) if exc.row else None
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "type": "polish_failed",
                    "message": str(exc),
                },
                "issue": draft_dto,
            },
        )
    except DigestOutputInvalid as exc:
        return JSONResponse(
            status_code=502,
            content={"error": {"type": "generation_failed", "message": str(exc)}},
        )
    except Exception as exc:  # noqa: BLE001 — typed mapping
        name = type(exc).__name__
        if name in {"AiNotConfigured", "AiAuthError", "AiModelError"}:
            return JSONResponse(
                status_code=409,
                content={
                    "error": {"type": "ai_not_configured", "message": "AI 未配置或配置不可用。"}
                },
            )
        if name in {"AiRateLimited", "AiTimeout", "AiUpstreamError"}:
            return JSONResponse(
                status_code=502,
                content={
                    "error": {"type": "ai_upstream", "message": "AI 上游暂时不可用。"}
                },
            )
        raise
    dto = _issues(request).issue_to_dto(row)
    return JSONResponse(status_code=200, content={"issue": dto})


@router.post("/api/v1/gpt-digest/configs/{config_id}/issues/{issue_key}/compare")
async def compare_gpt_digest_issue(
    config_id: int, issue_key: str, request: Request
) -> Response:
    """F07：相邻日报变化对照（对照上一期；独立条目 key = {key}-d）。"""
    from lumirss.gpt_digest import (
        DigestMaterialEmpty,
        DigestOutputInvalid,
        _build_ai_deps,
        compare_with_previous,
    )

    config = await _config_store(request).get_config(config_id)
    if config is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "not_found", "message": "配置不存在。"}},
        )
    ai_settings, provider_factory = _build_ai_deps(request.app.state)
    try:
        row = await compare_with_previous(
            _config_store(request),
            _issues(request),
            config=config,
            ai_settings=ai_settings,
            provider_factory=provider_factory,
            issue_key=issue_key,
        )
    except DigestMaterialEmpty as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "no_previous", "message": str(exc)}},
        )
    except DigestOutputInvalid as exc:
        return JSONResponse(
            status_code=502,
            content={"error": {"type": "generation_failed", "message": str(exc)}},
        )
    except Exception as exc:  # noqa: BLE001 — typed mapping
        if type(exc).__name__ in {"AiNotConfigured", "AiAuthError", "AiModelError"}:
            return JSONResponse(
                status_code=409,
                content={
                    "error": {"type": "ai_not_configured", "message": "AI 未配置或配置不可用。"}
                },
            )
        if type(exc).__name__ in {"AiRateLimited", "AiTimeout", "AiUpstreamError"}:
            return JSONResponse(
                status_code=502,
                content={"error": {"type": "ai_upstream", "message": "AI 上游暂时不可用。"}},
            )
        raise
    dto = _issues(request).issue_to_dto(row)
    return JSONResponse(status_code=200, content={"issue": dto})


@router.post("/api/v1/gpt-digest/configs/{config_id}/issues/{issue_key}/compare-facts")
async def compare_facts_gpt_digest_issue(
    config_id: int, issue_key: str, request: Request
) -> Response:
    """F28：事实对照——对某期内的条目按时间/主张/分歧生成对照表。

    按需生成、不落库（返回渲染 HTML + 结构化 sections + refs）；矛盾
    并列不裁决。AI 未配置/失败映射稳定错误。"""
    from lumirss.gpt_digest import (
        DigestMaterialEmpty,
        _build_ai_deps,
        compare_facts,
    )

    config = await _config_store(request).get_config(config_id)
    if config is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "not_found", "message": "配置不存在。"}},
        )
    ai_settings, provider_factory = _build_ai_deps(request.app.state)
    try:
        return JSONResponse(
            status_code=200,
            content={
                await compare_facts(
                    _issues(request),
                    config_id=config_id,
                    issue_key=issue_key,
                    ai_settings=ai_settings,
                    provider_factory=provider_factory,
                )
            },
        )
    except DigestMaterialEmpty as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "no_material", "message": str(exc)}},
        )
    except Exception as exc:  # noqa: BLE001 — typed mapping
        name = type(exc).__name__
        if name in {"AiNotConfigured", "AiAuthError", "AiModelError"}:
            return JSONResponse(
                status_code=409,
                content={
                    "error": {"type": "ai_not_configured", "message": "AI 未配置或配置不可用。"}
                },
            )
        if name in {"AiRateLimited", "AiTimeout", "AiUpstreamError", "AiInvalidResponse"}:
            return JSONResponse(
                status_code=502,
                content={"error": {"type": "ai_upstream", "message": str(exc)}},
            )
        raise


@router.get("/api/v1/gpt-digest/issues", response_model=GptDigestIssueList)
async def list_gpt_digest_issues(
    request: Request, limit: int = 14
) -> GptDigestIssueList:
    rows = await _issues(request).recent_issues(1, limit, include_drafts=True)
    return GptDigestIssueList(items=[_issues(request).issue_to_dto(row) for row in rows])


# -- F102 手工候选素材池 ------------------------------------------------------


def _pool_store(request: Request) -> DigestMaterialPoolStore:
    return DigestMaterialPoolStore(request.app.state.db)


class PoolAddBody(BaseModel):
    """POST …/pool 体：一条读者条目引用（rss: 前缀）。"""

    model_config = {"extra": "forbid"}

    entryRef: str = Field(min_length=1, max_length=512)


class PoolReorderBody(BaseModel):
    """PATCH …/pool 体：全量提交后的 id 顺序。"""

    model_config = {"extra": "forbid"}

    orderedIds: list[int] = Field(max_length=200)


@router.get("/api/v1/gpt-digest/configs/{config_id}/pool")
async def list_digest_pool(config_id: int, request: Request) -> dict:
    if await _config_store(request).get_config(config_id) is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "not_found", "message": "配置不存在。"}},
        )
    entries = await _pool_store(request).list_entries(config_id)
    pending = [e for e in entries if e["usedIssueKey"] is None]
    used = [e for e in entries if e["usedIssueKey"] is not None]
    return {"items": pending, "used": used}


@router.post("/api/v1/gpt-digest/configs/{config_id}/pool", status_code=201)
async def add_digest_pool_entry(
    config_id: int, payload: PoolAddBody, request: Request
) -> dict:
    """加入素材池。重复 → 409；AI 禁用来源的条目 → 422（F066 负向语义：
    服务端拒绝，不只靠 UI 隐藏）。"""
    if await _config_store(request).get_config(config_id) is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "not_found", "message": "配置不存在。"}},
        )
    from lumirss.source_ai_gate import disabled_entry_refs

    disabled = await disabled_entry_refs(request.app.state.db, [payload.entryRef])
    if disabled:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "ai_disabled_source",
                    "message": "该条目所属来源已禁用 AI 选材，不可加入日报素材池。",
                }
            },
        )
    try:
        entry = await _pool_store(request).add_entry(config_id, payload.entryRef)
    except DigestPoolDuplicate:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "duplicate",
                    "message": "该条目已在素材池中。",
                }
            },
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_request", "message": str(exc)}},
        )
    return entry


@router.delete("/api/v1/gpt-digest/configs/{config_id}/pool/{entry_id}", status_code=204)
async def remove_digest_pool_entry(
    config_id: int, entry_id: int, request: Request
) -> Response:
    removed = await _pool_store(request).remove_entry(config_id, entry_id)
    if not removed:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "not_found", "message": "池条目不存在。"}},
        )
    return Response(status_code=204)


@router.patch("/api/v1/gpt-digest/configs/{config_id}/pool")
async def reorder_digest_pool(
    config_id: int, payload: PoolReorderBody, request: Request
) -> dict:
    await _pool_store(request).reorder(config_id, payload.orderedIds)
    entries = await _pool_store(request).list_entries(config_id)
    return {"items": [e for e in entries if e["usedIssueKey"] is None]}


# -- 生成（配置共用） --------------------------------------------------------


async def _generate_for_config(
    request: Request, config: dict | None, *, put_back: list[str] | None = None
) -> Response:
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
            draft=True,
            put_back=put_back,
        )
    except DigestMaterialEmpty as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "no_material", "message": str(exc)}},
        )
    except DigestPolishFailed as exc:
        # N172：润色失败——选材/总结草稿已保留（响应携带该草稿），错误
        # 诚实带阶段名；可经 retry-polish 仅补润色。
        draft_dto = _issues(request).issue_to_dto(exc.row) if exc.row else None
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "type": "polish_failed",
                    "message": str(exc),
                },
                "issue": draft_dto,
            },
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
    if not expected or not verify_token(token, expected):
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
