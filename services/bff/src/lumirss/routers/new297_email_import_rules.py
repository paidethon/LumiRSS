"""NEW-297 邮件导入规则路由 — 样本预览（零写入）+ 规则清单管理。

- POST   /api/v1/email-imports/preview {files, rules?} → 样本变换预览
- GET    /api/v1/email-import-rules                    → 已保存规则清单
- POST   /api/v1/email-import-rules {kind, config}     → 保存一条规则
- DELETE /api/v1/email-import-rules/{ruleId}           → 删除规则
- 确认导入 = POST /api/v1/email-materials/import 携带同一 rules
  （routers/new291：与预览共用 apply_rules，预览不是另一个实现）。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lumirss.new297_email_import_rules import (
    ImportRuleStore,
    RuleInvalid,
)

router = APIRouter()


class PreviewBody(BaseModel):
    model_config = {"extra": "forbid"}

    files: list[dict]
    rules: list[dict] | None = None


class RuleBody(BaseModel):
    model_config = {"extra": "forbid"}

    kind: str
    config: dict = {}


@router.post("/api/v1/email-imports/preview")
async def post_import_preview(payload: PreviewBody, request: Request) -> Response:
    try:
        result = await ImportRuleStore(request.app.state.db).preview(
            payload.files, payload.rules
        )
    except RuleInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "import_rule_invalid", "message": str(exc)}},
        )
    return JSONResponse(result)


@router.get("/api/v1/email-import-rules")
async def get_import_rules(request: Request) -> Response:
    return JSONResponse(await ImportRuleStore(request.app.state.db).list_rules())


@router.post("/api/v1/email-import-rules")
async def post_import_rule(payload: RuleBody, request: Request) -> Response:
    try:
        rule = await ImportRuleStore(request.app.state.db).save_rule(
            {"kind": payload.kind, "config": payload.config}
        )
    except RuleInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "import_rule_invalid", "message": str(exc)}},
        )
    return JSONResponse(rule, status_code=201)


@router.delete("/api/v1/email-import-rules/{rule_id}", status_code=204)
async def delete_import_rule(rule_id: str, request: Request) -> Response:
    deleted = await ImportRuleStore(request.app.state.db).delete_rule(rule_id)
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={
                "error": {"type": "import_rule_not_found", "message": "没有这条规则。"}
            },
        )
    return Response(status_code=204)
