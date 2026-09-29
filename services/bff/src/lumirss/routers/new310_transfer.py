"""NEW-310 接入配置转移包路由。

- GET  /api/v1/api-sources/transfer-bundle            导出（无秘密）
- POST /api/v1/api-sources/transfer-bundle/import     导入（重选凭据引用）
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new310_transfer_bundle import (
    TransferAlreadyImported,
    TransferBundleInvalid,
    TransferBundleStore,
    export_bundle,
)

router = APIRouter()


def _stores(request: Request):
    from lumirss.api_source_store import ApiSourceStore

    return (
        ApiSourceStore(request.app.state.db),
        TransferBundleStore(request.app.state.db),
    )


class BundleImportBody(BaseModel):
    model_config = {"extra": "forbid"}

    bundle: dict = Field(min_length=1)
    credentials: dict[str, str] = Field(default_factory=dict)


@router.get("/api/v1/api-sources/transfer-bundle")
async def get_transfer_bundle(request: Request) -> Response:
    source_store, _ = _stores(request)
    return JSONResponse(await export_bundle(source_store))


@router.post("/api/v1/api-sources/transfer-bundle/import")
async def import_transfer_bundle(payload: BundleImportBody, request: Request) -> Response:
    source_store, bundle_store = _stores(request)
    try:
        result = await bundle_store.import_bundle(
            source_store, payload.bundle, payload.credentials
        )
    except TransferAlreadyImported as exc:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "already_imported",
                    "message": (
                        "该转移包已导入过（防重复导入）；"
                        f"首次导入时间 {exc.imported_at}，"
                        f"新建 {exc.created}、合并 {exc.merged}、跳过 {exc.skipped}。"
                    ),
                }
            },
        )
    except TransferBundleInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_transfer_bundle", "message": str(exc)}},
        )
    return JSONResponse(result)
