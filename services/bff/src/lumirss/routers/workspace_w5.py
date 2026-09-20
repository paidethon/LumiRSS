"""W5 workspace routes — F083 模板 / F084 归档 / F085 看板 / F086 目标.

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
    WorkspaceBoardResponse,
    WorkspaceFromTemplateResult,
    WorkspaceGoalPut,
    WorkspaceGoalView,
    WorkspacePatch,
    WorkspaceTemplate,
    WorkspaceTemplateList,
)
from lumirss.workspace_archive import ArchivedWorkspace, WorkspaceArchiveStore
from lumirss.workspace_board import WorkspaceBoardStore
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
        workspace_id, payload.name
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
    )
    workspace = result["workspace"]
    skipped = skipped + [
        r for r in result["skippedExampleRefs"] if r not in skipped
    ]
    return WorkspaceFromTemplateResult(
        workspace=_workspace_model(workspace),
        addedExampleRefs=result["addedExampleRefs"],
        skippedExampleRefs=skipped,
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


@router.get("/api/v1/workspace-archive", response_model=list)
async def list_archived_workspaces(request: Request) -> list:
    """F084 归档列表入口（默认导航隐藏，这里显式可见）。"""
    summaries = await _get_workspace_store(request).list_workspaces(
        include_archived=True
    )
    return [_workspace_model(s).model_dump() for s in summaries if s.archived]


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
    goal = await _goal_store(request).put_goal(
        workspace_id, payload.targetCount, payload.deadline
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
