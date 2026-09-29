"""NEW-344 共享链接使用范围路由 + 公开访问路由。

- POST /api/v1/me/share-links            创建（scope=titles/excerpt/full；
      full 需设备信任在有效期内——NEW-346 消费点）；明文 token 一次性
- GET  /api/v1/me/share-links            本人清单（绝无 token 材料）
- GET  /api/v1/me/share-links/{id}/preview   外部访问者视角预览（同一渲染）
- POST /api/v1/me/share-links/{id}/revoke    撤销
- GET  /shares/{token}                 公开免登录（token 错/撤销 → 404）

per-user：A 的链接 B 看不到、撤不掉；公开路由经 machine_user_context
解析归属用户后才进入其数据作用域。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.machine_auth import machine_user_context
from lumirss.new341_access_log import record_access_event
from lumirss.new344_share_links import (
    MAX_EXCERPT_CHARS,
    ShareLinkInvalid,
    ShareLinkStore,
    render_payload,
)
from lumirss.new345_share_link_limits import (
    ShareLinkLimitInvalid,
    clean_max_uses,
    evaluate_access,
    record_access,
)

router = APIRouter()


def _store(request: Request) -> ShareLinkStore:
    return ShareLinkStore(request.app.state.db)


async def _require_user(request: Request) -> str | None:
    from lumirss.config import LumiSettings
    from lumirss.routers.auth import _current_user_id

    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        return None
    return await _current_user_id(request)


def _error(status: int, err_type: str, message: str, **extra: object) -> JSONResponse:
    body: dict[str, object] = {"error": {"type": err_type, "message": message}}
    if extra:
        body["error"] = {**body["error"], **extra}  # type: ignore[assignment]
    return JSONResponse(status_code=status, content=body)


def _invalid(exc: ShareLinkInvalid) -> JSONResponse:
    return _error(422, "share_link_invalid", str(exc))


class CreateBody(BaseModel):
    model_config = {"extra": "forbid"}

    title: str = Field(min_length=1, max_length=80)
    scope: str
    entryRefs: list[str] = Field(min_length=1, max_length=50)
    excerptChars: int = Field(default=200, ge=20, le=MAX_EXCERPT_CHARS)
    maxUses: int | None = Field(default=None, ge=1, le=100000)


@router.post("/api/v1/me/share-links", response_model=None)
async def create_share_link(body: CreateBody, request: Request) -> JSONResponse:
    user_id = await _require_user(request)
    if user_id is None:
        return _error(401, "session_required", "Login required.")
    if body.scope == "full":
        # NEW-346 消费点：对外发布完整授权正文要求设备信任在有效期内。
        from lumirss.new346_device_trust import (
            TRUST_PURPOSE_FULL_SHARE,
            current_grant,
            fingerprint_of_request,
            is_trusted,
        )

        fingerprint, _label = fingerprint_of_request(request)
        grant = await current_grant(request.app.state.db, fingerprint)
        if not is_trusted(grant):
            return _error(
                403,
                "device_trust_required",
                "发布「完整授权正文」是敏感操作：请先在当前设备完成"
                " POST /api/v1/me/device-trust（密码复核）。",
                purpose=TRUST_PURPOSE_FULL_SHARE,
            )
    try:
        max_uses = clean_max_uses(body.maxUses)
        created = await _store(request).create(
            title=body.title,
            scope=body.scope,
            entry_refs=body.entryRefs,
            excerpt_chars=body.excerptChars,
            max_uses=max_uses,
        )
    except ShareLinkInvalid as exc:
        return _invalid(exc)
    except ShareLinkLimitInvalid as exc:
        return _error(422, "share_link_invalid", str(exc))
    # 公开路由经 machine_user_context 解析归属用户 —— 与 NEW-285 私有
    # feed 同一机制：token 只入控制库哈希索引（明文一次性返回）。
    from lumirss.machine_auth import index_machine_token

    await index_machine_token(request, created["token"], "share_link")
    return JSONResponse(created, status_code=201, headers={"Cache-Control": "no-store"})


@router.get("/api/v1/me/share-links", response_model=None)
async def list_share_links(request: Request) -> JSONResponse:
    user_id = await _require_user(request)
    if user_id is None:
        return _error(401, "session_required", "Login required.")
    links = await _store(request).list_links()
    return JSONResponse(
        {
            "items": links,
            "note": "清单不含任何 token 材料；scope 创建后不可变（改范围请重建链接）。",
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/api/v1/me/share-links/{link_id}/preview", response_model=None)
async def preview_share_link(link_id: int, request: Request) -> JSONResponse:
    """外部访问者将看到的确切载荷（同一渲染函数；不计次不留痕）。"""
    user_id = await _require_user(request)
    if user_id is None:
        return _error(401, "session_required", "Login required.")
    link = await _store(request).get(link_id)
    if link is None:
        return _error(404, "share_link_not_found", "共享链接不存在。")
    entries = await _store(request).link_entries(link_id)
    payload = render_payload(link, entries)
    payload["linkState"] = {
        "revoked": link["revokedAt"] is not None,
        "useCount": link["useCount"],
        "maxUses": link["maxUses"],
        "exhaustedAt": link["exhaustedAt"],
    }
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@router.post("/api/v1/me/share-links/{link_id}/revoke", response_model=None)
async def revoke_share_link(link_id: int, request: Request) -> JSONResponse:
    user_id = await _require_user(request)
    if user_id is None:
        return _error(401, "session_required", "Login required.")
    revoked = await _store(request).revoke(link_id)
    if not revoked:
        return _error(404, "share_link_not_found", "共享链接不存在或已撤销。")
    from lumirss.new347_authorization_center import record_revoke

    await record_revoke(request.app.state.db, "share_link", str(link_id))
    return JSONResponse({"id": link_id, "revoked": True})


@router.get("/shares/{token}", response_model=None)
async def public_share(token: str, request: Request) -> JSONResponse:
    """公开免登录访问：范围渲染 + 次数判定（345）+ 访问留痕（341/345）。

    未知 token 与已撤销 → 同一 404（不泄露存在性，也就没有可记录的
    事实）；耗尽 → 410（留痕 result=limit_reached）。"""
    from lumirss.new345_share_link_limits import list_accesses  # noqa: F401

    async with machine_user_context(request, token) as uid:
        if uid is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"type": "not_found", "message": "not found"}},
            )
        store = _store(request)
        link = await store.resolve_by_token(token)
        if link is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"type": "not_found", "message": "not found"}},
            )
        verdict = evaluate_access(link)
        if verdict == "limit_reached":
            await record_access(request.app.state.db, link["id"], "limit_reached")
            return JSONResponse(
                status_code=410,
                content={
                    "error": {
                        "type": "share_link_exhausted",
                        "message": "该共享链接的使用次数已耗尽。",
                    }
                },
            )
        entries = await store.link_entries(link["id"])
        await record_access(request.app.state.db, link["id"], "served")
        await record_access_event(
            request.app.state.db, "share_link", f"链接 {link['title']}"
        )
        return JSONResponse(render_payload(link, entries))
