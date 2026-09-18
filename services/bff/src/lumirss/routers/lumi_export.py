"""F39 Lumi 自有数据可携带导出路由（只读 JSON 下载）。"""

import json

from fastapi import APIRouter, Request, Response

from lumirss.lumi_data_export import build_lumi_data_export
from lumirss.util import utc_now

router = APIRouter()


@router.get("/api/v1/export/lumi-data")
async def export_lumi_data(request: Request) -> Response:
    """可携带导出：工作区/标签/书签笔记/日报配置与期刊（版本化 JSON）。

    与运维备份（全量归档）和 FreshRSS OPML 导出用途分开；不包含服务
    密钥、订阅 token、Agent 会话/审批与 Vault 内容。"""
    data = await build_lumi_data_export(request.app.state.db)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    stamp = utc_now()[:10]
    return Response(
        content=payload,
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="lumirss-data-{stamp}.json"'
        },
    )
