"""NEW-207 RSSHub 参数表单 —— 依据路由参数定义的表单化添加（零手拼 URL）。

与既有面的分工（不重复造轮子）：

- 路由目录 + 参数定义：Lumi 自有 catalog（:data:`lumirss.rsshub.CATALOG`，
  GET /api/v1/rsshub/routes 已暴露）；本模块把它变成**表单契约**：
  每参数的 required/pattern/example/help + 服务端逐参数校验结果；
- 预览取样本：既有 POST /api/v1/rsshub/preview（含 N025 时间线 /
  N021 最近使用 / N027 缓存——本模块绝不复制这条管线）；
- 本模块补的缺口：**验证后添加**的最后一公里——表单参数 → 服务端
  逐参数校验（required/pattern/unknown，离线）→ 生成的订阅地址
  （``RSSHUB_FRESHRSS_BASE_URL + path``，与 preview 同源同构）→
  一次显式确认即订阅（409 已订；422 表单未过校验），并落一行脱敏
  使用台账。

安全属性：参数值只以脱敏形态落台账（mask_params，敏感键 '***'）；
URL 拼装只在服务端（浏览器永不接触 RSSHUB base 配置）。
"""

import json
import re
import uuid as _uuid
from typing import Any

from lumirss.rsshub import RssHubRoute, build_path
from lumirss.rsshub_route_store import mask_params
from lumirss.storage import Database
from lumirss.util import utc_now


class RssHubFormInvalid(ValueError):
    """表单非法（未知路由/参数校验失败），路由层映射 422。"""


def form_schema(route: RssHubRoute) -> dict[str, Any]:
    """路由 → 表单 schema（离线、纯派生）。"""
    return {
        "routeId": route.id,
        "title": route.title,
        "description": route.description,
        "pathTemplate": route.path_template,
        "parameters": [
            {
                "key": p.key,
                "label": p.label,
                "required": p.required,
                "pattern": p.pattern,
                "example": p.example,
                "help": p.help,
            }
            for p in route.parameters
        ],
    }


def validate_form(route: RssHubRoute, params: Any) -> dict[str, Any]:
    """逐参数校验（离线）：unknown / missing / pattern；全部通过才给
    generatedPath（复用既有 build_path，二次兜底）。纯函数。"""
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise RssHubFormInvalid("params 必须是对象。")
    known = {p.key: p for p in route.parameters}
    errors: list[dict[str, str]] = []
    unknown = sorted(set(map(str, params)) - set(known))
    for key in unknown:
        errors.append({"key": key, "code": "unknown", "message": "路由没有这个参数。"})
    for key, parameter in known.items():
        value = params.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            if parameter.required:
                errors.append(
                    {"key": key, "code": "missing_required", "message": "必填参数。"}
                )
            continue
        if not isinstance(value, str) or not re.fullmatch(parameter.pattern, value):
            errors.append(
                {
                    "key": key,
                    "code": "pattern_mismatch",
                    "message": f"不符合格式要求（示例：{parameter.example}）。",
                }
            )
    result: dict[str, Any] = {
        "routeId": route.id,
        "valid": not errors,
        "errors": errors,
    }
    if not errors:
        result["generatedPath"] = build_path(route, {str(k): str(v) for k, v in params.items()})
    return result


def _row_to_use(row: Any) -> dict[str, Any]:
    try:
        params = json.loads(str(row["params_json"]))
    except (json.JSONDecodeError, TypeError):
        params = {}
    return {
        "id": str(row["id"]),
        "routeId": str(row["route_id"]),
        "params": params if isinstance(params, dict) else {},
        "feedUrl": str(row["feed_url"]),
        "createdAt": str(row["created_at"]),
    }


class RssHubFormStore:
    """使用台账（脱敏参数；inline literal at each execute site）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self, *, route_id: str, params: dict[str, str], feed_url: str
    ) -> dict[str, Any]:
        use_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO new207_rsshub_form_uses"
            " (id, route_id, params_json, feed_url, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                use_id,
                route_id,
                json.dumps(mask_params({str(k): str(v) for k, v in params.items()}), ensure_ascii=False),
                feed_url,
                now,
            ),
        )
        return {
            "id": use_id,
            "routeId": route_id,
            "params": mask_params({str(k): str(v) for k, v in params.items()}),
            "feedUrl": feed_url,
            "createdAt": now,
        }

    async def list_uses(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, route_id, params_json, feed_url, created_at"
            " FROM new207_rsshub_form_uses ORDER BY created_at DESC, id DESC LIMIT 50",
            (),
        )
        return [_row_to_use(row) for row in rows]
