"""NEW-229 阅读约定卡路由。

双方各持一行（同一 pactKey 锚定）、各自独立确认；对方的确认状态
诚实呈现为 unavailable-cross-user（本部署无跨账户共享表面）。
稳定错误信封：invalid_reading_pact / reading_pact_not_found。
"""

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from lumirss.new229_reading_pacts import (
    PactInvalid,
    PactNotFound,
    ReadingPactStore,
)

router = APIRouter()


def _store(request: Request) -> ReadingPactStore:
    return ReadingPactStore(request.app.state.db)


class PactCreateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    itemRef: str
    deadline: str
    counterpartUsername: str = Field(min_length=1, max_length=60)
    materialTitle: str | None = Field(default=None, max_length=200)


class PactView(BaseModel):
    id: str
    pactKey: str
    itemRef: str
    materialTitle: str | None = None
    deadline: str
    counterpartUsername: str
    myStatus: str
    confirmedAt: str | None = None
    createdAt: str
    updatedAt: str
    counterpartVisibility: str
    """恒为 unavailable-cross-user：对方确认状态在本部署不可见（诚实）。"""


class PactCreateResponse(PactView):
    pass


class PactJoinRequest(BaseModel):
    model_config = {"extra": "forbid"}

    pactKey: str
    itemRef: str
    deadline: str
    counterpartUsername: str = Field(min_length=1, max_length=60)
    materialTitle: str | None = Field(default=None, max_length=200)


class PactConfirmRequest(BaseModel):
    model_config = {"extra": "forbid"}

    confirmed: bool


class PactArchiveRequest(BaseModel):
    model_config = {"extra": "forbid"}

    archived: bool


class PactListResponse(BaseModel):
    items: list[PactView]
    counterpartVisibility: str
    note: str


@router.post("/api/v1/reading/pacts", response_model=PactCreateResponse, status_code=201)
async def create_reading_pact(
    payload: PactCreateRequest, request: Request
) -> PactCreateResponse:
    """发起阅读约定（生成共持 pactKey，应用外交接给对方）。"""
    row = await _store(request).create(
        payload.itemRef,
        payload.deadline,
        payload.counterpartUsername,
        payload.materialTitle,
    )
    return PactCreateResponse(**row)


@router.post("/api/v1/reading/pacts/join", response_model=PactCreateResponse, status_code=201)
async def join_reading_pact(
    payload: PactJoinRequest, request: Request
) -> PactCreateResponse:
    """以共持 pactKey 在自己库里建对称行（同 key 重复 join 幂等 201）。"""
    row = await _store(request).join(
        payload.pactKey,
        payload.itemRef,
        payload.deadline,
        payload.counterpartUsername,
        payload.materialTitle,
    )
    return PactCreateResponse(**row)


@router.get("/api/v1/reading/pacts", response_model=PactListResponse)
async def list_reading_pacts(
    request: Request, includeArchived: bool = False
) -> PactListResponse:
    """我的约定清单（对方可见性诚实标注）。"""
    return PactListResponse(**await _store(request).list_pacts(include_archived=includeArchived))


@router.post("/api/v1/reading/pacts/{pact_id}/confirm", response_model=PactView)
async def confirm_reading_pact(
    pact_id: str, payload: PactConfirmRequest, request: Request
) -> PactView:
    """独立确认完成（set 语义；只能确认自己的行）。"""
    row = await _store(request).confirm(pact_id, payload.confirmed)
    return PactView(**row)


@router.post("/api/v1/reading/pacts/{pact_id}/archive", response_model=PactView)
async def archive_reading_pact(
    pact_id: str, payload: PactArchiveRequest, request: Request
) -> PactView:
    """归档/取消归档（set 语义）。"""
    row = await _store(request).archive(pact_id, payload.archived)
    return PactView(**row)


@router.delete("/api/v1/reading/pacts/{pact_id}", status_code=204)
async def delete_reading_pact(pact_id: str, request: Request) -> Response:
    """删除自己库里的约定行（显式动作；不影响对方的行）。"""
    await _store(request).delete(pact_id)
    return Response(status_code=204)


__all__ = ["router", "PactInvalid", "PactNotFound"]
