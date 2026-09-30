"""NEW-387 个人资料包加密导出路由 — 生成（含创建时解密校验）/ 校验 /
台账。

- POST /api/v1/preservation/encrypted-exports   {itemIds, passphrase}
  → 加密包 base64 + 一次解密校验结论（口令只在本次请求内使用，绝不
  落库/写日志；包本体不保存在服务端）
- POST /api/v1/preservation/encrypted-exports/verify
  {payloadBase64, passphrase} → 用户自行保存的包回传校验（口令同样
  即用即弃）
- GET  /api/v1/preservation/encrypted-exports → 台账（仅参数与摘要，
  无口令、无包本体）
"""

import base64
import binascii
from typing import Any

from fastapi import APIRouter, Request

from lumirss.new387_encrypted_export import (
    EncryptedExportInvalid,
    create_encrypted_export,
    decrypt,
    list_exports,
    verify_zip,
)
from lumirss.routers.preservation_gate import (
    error_response,
    no_store,
    require_preservation_user,
)

router = APIRouter()


@router.post("/api/v1/preservation/encrypted-exports")
async def create_encrypted(payload: dict[str, Any], request: Request) -> Any:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    raw_ids = payload.get("itemIds")
    ids = [str(ref) for ref in raw_ids] if isinstance(raw_ids, list) else []
    passphrase = payload.get("passphrase")
    try:
        return no_store(
            await create_encrypted_export(request.app.state.db, ids, str(passphrase or ""))
        )
    except EncryptedExportInvalid as exc:
        return error_response(400, "invalid_encrypted_export", str(exc))


@router.post("/api/v1/preservation/encrypted-exports/verify")
async def verify_encrypted(payload: dict[str, Any], request: Request) -> Any:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    passphrase = str(payload.get("passphrase") or "")
    try:
        blob = base64.b64decode(str(payload.get("payloadBase64") or ""), validate=True)
    except (binascii.Error, ValueError):
        return error_response(400, "invalid_encrypted_export", "包内容不是有效的 base64。")
    try:
        roundtrip, _params = decrypt(blob, passphrase)
        summary = verify_zip(roundtrip)
    except EncryptedExportInvalid as exc:
        return error_response(400, "decrypt_failed", str(exc))
    return no_store(
        {
            "decryptVerified": True,
            "itemCount": summary["itemCount"],
            "payloadSha256": summary["payloadSha256"],
            "note": "校验通过：口令正确、包完整。口令未被保存或记录。",
        }
    )


@router.get("/api/v1/preservation/encrypted-exports")
async def list_encrypted(request: Request) -> Any:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    return no_store({"exports": await list_exports(request.app.state.db)})
