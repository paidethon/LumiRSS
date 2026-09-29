"""NEW-318 剪藏图片选择器路由 — 图片清单 / 勾选保存 / 勾选台账。

- POST /api/v1/library/clips/image-manifest {url}                    → 200 清单（零写入）
- POST /api/v1/library/clips/curated {url, selectedImages[]}         → 201 剪藏 + 勾选台账
- GET  /api/v1/library/clips/{item_uuid}/image-selection             → 勾选台账

抓取/探测可经 app.state 注入（测试）；生产走默认有界 SSRF 管线。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.clip_fetch import ClipFetchError
from lumirss.library_clips import ClipInvalid
from lumirss.new318_image_picker import (
    ImageListInvalid,
    ImagePickerError,
    ImagePickerService,
)

router = APIRouter()


class ManifestBody(BaseModel):
    model_config = {"extra": "forbid"}

    url: str = Field(min_length=1, max_length=2048)


class CuratedBody(BaseModel):
    model_config = {"extra": "forbid"}

    url: str = Field(min_length=1, max_length=2048)
    selectedImages: list[str] = Field(default=[], max_length=50)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _service(request: Request) -> ImagePickerService:
    return ImagePickerService(
        request.app.state.db,
        fetcher=getattr(request.app.state, "image_picker_fetcher", None),
        size_prober=getattr(request.app.state, "image_picker_prober", None),
    )


@router.post("/api/v1/library/clips/image-manifest")
async def image_manifest(payload: ManifestBody, request: Request) -> Response:
    try:
        return JSONResponse(await _service(request).manifest(payload.url))
    except ImageListInvalid as exc:
        return _error(422, "invalid_image_payload", str(exc))
    except (ImagePickerError, ClipFetchError) as exc:
        return _error(
            502, "clip_fetch_failed", f"页面抓取失败：{exc}。未生成清单。"
        )


@router.post("/api/v1/library/clips/curated", status_code=201)
async def create_curated_clip(payload: CuratedBody, request: Request) -> Response:
    try:
        return JSONResponse(
            await _service(request).curate(payload.url, payload.selectedImages),
            status_code=201,
        )
    except ImageListInvalid as exc:
        return _error(422, "invalid_image_payload", str(exc))
    except (ImagePickerError, ClipFetchError) as exc:
        return _error(502, "clip_fetch_failed", f"页面抓取失败：{exc}。未保存。")
    except ClipInvalid as exc:
        return _error(422, "invalid_clip_payload", str(exc))


@router.get("/api/v1/library/clips/{item_uuid}/image-selection")
async def get_image_selection(item_uuid: str, request: Request) -> Response:
    result = await _service(request).last_selection(item_uuid)
    if result is None:
        return _error(404, "image_selection_not_found", "该剪藏没有图片勾选记录。")
    return JSONResponse(result)
