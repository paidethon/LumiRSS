"""W5 workspace routes — F083 模板 / F084 归档 / F085 看板 / F086 目标
+ N117 模板结构承载 + N118 收集规则 + N119 归档摘要卡.

归档工作区：默认列表隐藏（archived 参数显式拉取）；深链接可打开；
research-pack / 看板写入 / 目标写入入口对归档工作区诚实禁用（409
archived_workspace）。保留工作区（read-later）归档 → protected_workspace。
"""

from fastapi import APIRouter, Request, Response

from lumirss.models import (
    BoardColumn,
    BoardUpdateRequest,
    FromTemplateRequest,
    SaveAsTemplateRequest,
    WorkspaceArchiveEntry,
    WorkspaceArchiveSummary,
    WorkspaceBoardResponse,
    WorkspaceCollectApplyResult,
    WorkspaceCollectPreview,
    WorkspaceCollectPreviewItem,
    WorkspaceCollectRule,
    WorkspaceCollectRuleCreate,
    WorkspaceCollectRuleEnabledPatch,
    WorkspaceCollectRuleList,
    WorkspaceFromTemplateResult,
    WorkspaceGoalPut,
    WorkspaceGoalView,
    WorkspacePatch,
    WorkspaceTemplate,
    WorkspaceTemplateList,
)
from lumirss.workspace_archive import ArchivedWorkspace, WorkspaceArchiveStore
from lumirss.workspace_board import WorkspaceBoardStore
from lumirss.workspace_collect_rules import (
    CollectRuleNotFound,
    WorkspaceCollectRuleStore,
)
from lumirss.workspace_goals import WorkspaceGoalStore
from lumirss.workspace_templates import WorkspaceTemplateStore
from lumirss.workspaces import (
    WorkspaceInvalid,
    WorkspaceNotFound,
)

from ..deps import _get_source_registry, _get_workspace_store

router = APIRouter()


def _template_store(request: Request) -> WorkspaceTemplateStore:
    return WorkspaceTemplateStore(
        request.app.state.db, _get_workspace_store(request)
    )


def _collect_store(request: Request) -> WorkspaceCollectRuleStore:
    return WorkspaceCollectRuleStore(
        request.app.state.db, _get_workspace_store(request)
    )


def _archive_store(request: Request) -> WorkspaceArchiveStore:
    return WorkspaceArchiveStore(
        request.app.state.db, _get_workspace_store(request)
    )


def _board_store(request: Request) -> WorkspaceBoardStore:
    return WorkspaceBoardStore(
        request.app.state.db, _get_workspace_store(request)
    )


def _goal_store(request: Request) -> WorkspaceGoalStore:
    return WorkspaceGoalStore(
        request.app.state.db, _get_workspace_store(request)
    )


async def _require_active(request: Request, workspace_id: str):
    """归档工作区的写入口：409 archived_workspace（诚实禁用）。"""
    summary = await _get_workspace_store(request).get_workspace(workspace_id)
    if summary is None:
        raise WorkspaceNotFound(workspace_id)
    if summary.archived:
        raise ArchivedWorkspace(workspace_id)
    return summary


# -- F083 模板 ----------------------------------------------------------------


@router.post(
    "/api/v1/workspaces/{workspace_id}/save-as-template",
    response_model=WorkspaceTemplate,
    status_code=201,
)
async def save_as_template(
    workspace_id: str, payload: SaveAsTemplateRequest, request: Request
) -> WorkspaceTemplate:
    await _require_active(request, workspace_id)
    template = await _template_store(request).save_as_template(
        workspace_id,
        payload.name,
        include_structure=payload.includeStructure,
    )
    return WorkspaceTemplate(**template)


@router.post(
    "/api/v1/workspaces/from-template",
    response_model=WorkspaceFromTemplateResult,
    status_code=201,
)
async def create_from_template(
    payload: FromTemplateRequest, request: Request
) -> WorkspaceFromTemplateResult:
    # F083：示例条目以 ref 引用（不复制内容）；失效 ref 诚实跳过
    #（先过 Source Registry 可解析性，与手工加入工作区同契约）。
    resolvable: list[str] = []
    skipped: list[str] = []
    if payload.includeExampleItems:
        from lumirss.sources import ItemRefUnresolvable, ensure_resolvable

        registry = _get_source_registry(request)
        for ref in payload.exampleRefs:
            try:
                await ensure_resolvable(registry, ref)
            except (ItemRefUnresolvable, ValueError):
                skipped.append(ref)
                continue
            resolvable.append(ref)
    result = await _template_store(request).create_from_template(
        template_id=payload.templateId,
        name=payload.name,
        include_example_items=payload.includeExampleItems,
        example_refs=resolvable,
        include_structure=payload.includeStructure,
    )
    workspace = result["workspace"]
    skipped = skipped + [
        r for r in result["skippedExampleRefs"] if r not in skipped
    ]
    return WorkspaceFromTemplateResult(
        workspace=_workspace_model(workspace),
        addedExampleRefs=result["addedExampleRefs"],
        skippedExampleRefs=skipped,
        structure=result.get("structure"),
    )


@router.get("/api/v1/workspace-templates", response_model=WorkspaceTemplateList)
async def list_templates(request: Request) -> WorkspaceTemplateList:
    return WorkspaceTemplateList(
        items=[
            WorkspaceTemplate(**t)
            for t in await _template_store(request).list_templates()
        ]
    )


@router.delete("/api/v1/workspace-templates/{template_id}", status_code=204)
async def delete_template(template_id: str, request: Request) -> Response:
    deleted = await _template_store(request).delete_template(template_id)
    if not deleted:
        from lumirss.workspace_templates import TemplateNotFound

        raise TemplateNotFound(template_id)
    return Response(status_code=204)


def _workspace_model(summary):
    from lumirss.models import Workspace

    return Workspace(
        id=summary.id,
        name=summary.name,
        position=summary.position,
        itemCount=summary.item_count,
        reserved=summary.reserved,
        description=summary.description,
        archived=summary.archived,
        archivedAt=summary.archived_at,
    )


# -- F084 归档 ----------------------------------------------------------------


@router.patch("/api/v1/workspaces/{workspace_id}/archive")
async def patch_workspace_archive(
    workspace_id: str, payload: WorkspacePatch, request: Request
):
    """F084：archived=true 归档 / false 恢复（本路由不改名——与既有
    PATCH /workspaces/{id} 分工明确）。"""
    if payload.archived is None:
        raise WorkspaceInvalid("archived 字段必填（true=归档 / false=恢复）。")
    store = _archive_store(request)
    try:
        if payload.archived:
            return await store.archive(workspace_id)
        return await store.restore(workspace_id)
    except KeyError as exc:
        raise WorkspaceNotFound(workspace_id) from exc


@router.get("/api/v1/workspace-archive", response_model=list[WorkspaceArchiveEntry])
async def list_archived_workspaces(request: Request) -> list:
    """F084 归档列表入口（默认导航隐藏，这里显式可见）。

    N119：每个归档工作区附摘要卡（itemCount / doneCount / goalProgress
    / archivedAt / daysActive）——全部从真实行派生，绝不估算。"""
    summaries = await _get_workspace_store(request).list_workspaces(
        include_archived=True
    )
    entries: list[WorkspaceArchiveEntry] = []
    for summary in summaries:
        if not summary.archived:
            continue
        model = _workspace_model(summary)
        entries.append(
            WorkspaceArchiveEntry(
                **model.model_dump(),
                summary=await _archive_summary(request, summary),
            )
        )
    return entries


async def _archive_summary(request: Request, summary) -> WorkspaceArchiveSummary:
    """N119 摘要：成员数 / 看板 done / 目标进度 / 存续天数。"""
    from datetime import datetime

    db = request.app.state.db
    await db.migrate()
    item_row = await db.fetch_one(
        "SELECT COUNT(*) AS n FROM workspace_items WHERE workspace_id = ?",
        (summary.id,),
    )
    done = await _board_store(request).done_count(summary.id)
    goal = await _goal_store(request).get_goal(summary.id)
    days_active = 0
    created_row = await db.fetch_one(
        "SELECT created_at FROM workspaces WHERE id = ?", (summary.id,)
    )
    if summary.archived_at and created_row is not None:
        try:
            start = datetime.fromisoformat(
                str(created_row["created_at"]).replace("Z", "+00:00")
            )
            end = datetime.fromisoformat(
                str(summary.archived_at).replace("Z", "+00:00")
            )
            days_active = max((end - start).days, 0)
        except ValueError:
            days_active = 0  # 损坏时间戳诚实归零，绝不 500
    return WorkspaceArchiveSummary(
        itemCount=int(item_row["n"]) if item_row is not None else 0,
        doneCount=done,
        goalProgress=(
            {"targetCount": int(goal["targetCount"]), "doneCount": done}
            if goal is not None
            else None
        ),
        archivedAt=summary.archived_at,
        daysActive=days_active,
    )


# -- F085 看板 ----------------------------------------------------------------


@router.get("/api/v1/workspaces/{workspace_id}/board")
async def get_board(workspace_id: str, request: Request) -> WorkspaceBoardResponse:
    summary = await _get_workspace_store(request).get_workspace(workspace_id)
    if summary is None:
        raise WorkspaceNotFound(workspace_id)
    board = await _board_store(request).get_board(workspace_id)
    return WorkspaceBoardResponse(
        workspaceId=board["workspaceId"],
        columns=[BoardColumn(**column) for column in board["columns"]],
    )


@router.put("/api/v1/workspaces/{workspace_id}/board")
async def put_board(
    workspace_id: str, payload: BoardUpdateRequest, request: Request
):
    await _require_active(request, workspace_id)
    store = _board_store(request)
    return await store.set_status(workspace_id, payload.itemRef, payload.status)


# -- F086 目标 ----------------------------------------------------------------


@router.get("/api/v1/workspaces/{workspace_id}/goal")
async def get_goal(workspace_id: str, request: Request):
    summary = await _get_workspace_store(request).get_workspace(workspace_id)
    if summary is None:
        raise WorkspaceNotFound(workspace_id)
    goal = await _goal_store(request).get_goal(workspace_id)
    if goal is None:
        return {"exists": False}
    done = await _board_store(request).done_count(workspace_id)
    return WorkspaceGoalView(**goal, doneCount=done).model_dump()


@router.put("/api/v1/workspaces/{workspace_id}/goal")
async def put_goal(
    workspace_id: str, payload: WorkspaceGoalPut, request: Request
):
    await _require_active(request, workspace_id)
    # N111：goalText / conditions 「键未出现」= 保留既有值（旧调用方
    # 绝不无意清空）；显式 null/空串/空数组 = 清除（fields_set 区分）。
    goal = await _goal_store(request).put_goal(
        workspace_id,
        payload.targetCount,
        payload.deadline,
        payload.goalText,
        payload.conditions,
        goal_text_set="goalText" in payload.model_fields_set,
        conditions_set="conditions" in payload.model_fields_set,
    )
    done = await _board_store(request).done_count(workspace_id)
    return WorkspaceGoalView(**goal, doneCount=done).model_dump()


@router.delete("/api/v1/workspaces/{workspace_id}/goal", status_code=204)
async def delete_goal(workspace_id: str, request: Request) -> Response:
    summary = await _get_workspace_store(request).get_workspace(workspace_id)
    if summary is None:
        raise WorkspaceNotFound(workspace_id)
    await _goal_store(request).delete_goal(workspace_id)
    return Response(status_code=204)


# -- N118 工作区自动收集规则 ---------------------------------------------------


def _rule_model(rule: dict) -> WorkspaceCollectRule:
    return WorkspaceCollectRule(
        id=rule["id"],
        workspaceId=rule["workspaceId"],
        feedUrl=rule["feedUrl"],
        tag=rule["tag"],
        keyword=rule["keyword"],
        enabled=rule["enabled"],
        maxItems=rule["maxItems"],
        addedCount=rule["addedCount"],
        createdAt=rule["createdAt"],
        updatedAt=rule["updatedAt"],
    )


@router.get(
    "/api/v1/workspaces/{workspace_id}/collect-rules",
    response_model=WorkspaceCollectRuleList,
)
async def list_collect_rules(
    workspace_id: str, request: Request
) -> WorkspaceCollectRuleList:
    """N118：规则列表（created_at 升序）。未知工作区 → 404。"""
    rules = await _collect_store(request).list_rules(workspace_id)
    return WorkspaceCollectRuleList(items=[_rule_model(r) for r in rules])


@router.post(
    "/api/v1/workspaces/{workspace_id}/collect-rules",
    response_model=WorkspaceCollectRule,
    status_code=201,
)
async def create_collect_rule(
    workspace_id: str, payload: WorkspaceCollectRuleCreate, request: Request
) -> WorkspaceCollectRule:
    """N118：创建规则（feedUrl | tag | keyword 恰好其一；maxItems ≤100）。

    规则只是条件 + 上限 + 开关，绝不后台执行——收集只由显式 apply
    触发（手动按钮语义，见模块注释）。"""
    rule = await _collect_store(request).create_rule(
        workspace_id,
        feed_url=payload.feedUrl,
        tag=payload.tag,
        keyword=payload.keyword,
        max_items=payload.maxItems,
        enabled=payload.enabled,
    )
    return _rule_model(rule)


@router.patch(
    "/api/v1/workspaces/{workspace_id}/collect-rules/{rule_id}",
    response_model=WorkspaceCollectRule,
)
async def patch_collect_rule(
    workspace_id: str,
    rule_id: str,
    payload: WorkspaceCollectRuleEnabledPatch,
    request: Request,
) -> WorkspaceCollectRule:
    """N118：暂停/恢复（enabled set 语义；不触碰 added_count）。"""
    rule = await _collect_store(request).set_enabled(
        workspace_id, rule_id, payload.enabled
    )
    return _rule_model(rule)


@router.delete(
    "/api/v1/workspaces/{workspace_id}/collect-rules/{rule_id}", status_code=204
)
async def delete_collect_rule(
    workspace_id: str, rule_id: str, request: Request
) -> Response:
    deleted = await _collect_store(request).delete_rule(workspace_id, rule_id)
    if not deleted:
        raise CollectRuleNotFound(rule_id)
    return Response(status_code=204)


@router.post(
    "/api/v1/workspaces/{workspace_id}/collect-rules/{rule_id}/preview",
    response_model=WorkspaceCollectPreview,
)
async def preview_collect_rule(
    workspace_id: str, rule_id: str, request: Request
) -> WorkspaceCollectPreview:
    """N118：预演（dry-run，有界 50）——投影实时匹配，绝不写库、
    绝不触发上游抓取。"""
    store = _collect_store(request)
    preview = await store.preview(workspace_id, rule_id)
    return WorkspaceCollectPreview(
        ruleId=preview["ruleId"],
        matches=[
            WorkspaceCollectPreviewItem(
                itemRef=match["itemRef"],
                title=match["title"],
                feedTitle=match["feedTitle"],
                publishedAt=match["publishedAt"],
                alreadyMember=match["alreadyMember"],
            )
            for match in preview["matches"]
        ],
        matchCount=preview["matchCount"],
        bounded=preview["bounded"],
        alreadyMemberCount=preview["alreadyMemberCount"],
        remainingCap=preview["remainingCap"],
    )


@router.post(
    "/api/v1/workspaces/{workspace_id}/collect-rules/{rule_id}/apply",
    response_model=WorkspaceCollectApplyResult,
)
async def apply_collect_rule(
    workspace_id: str, rule_id: str, request: Request
) -> WorkspaceCollectApplyResult:
    """N118：手动应用——命中条目以 ref 引用进工作区（幂等；受规则
    ``maxItems`` 累计上限约束；暂停规则零新增并诚实回显 enabled）。"""
    result = await _collect_store(request).apply(workspace_id, rule_id)
    return WorkspaceCollectApplyResult(**result)
