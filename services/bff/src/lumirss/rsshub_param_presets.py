"""N030 路由可复用参数方案 — 每用户私有的 RSSHub 参数预设（CRUD + 回填）。

方案 = 命名的参数组合（模板参数 + query 参数都可以），保存后可一键
回填参数表单（create-draft）。安全属性与收藏/最近使用（N021）完全
一致：``mask_params`` 用与 Web F047 相同的敏感键规则把敏感参数值
替换为 '***' 哨兵——真实值从不落盘，因此「应用」一个含敏感参数的
方案时那些键必须重新输入（requiresRebind），回填的哨兵值会被服务端
pattern 校验拒绝。方案按用户库天然隔离（迁移 0121 落每用户库）。

cap：每用户最多 MAX_PRESETS 个方案；超限是稳定错误
（rsshub_param_preset_limit），绝不静默淘汰旧方案。

SQL stays an inline literal at each execute site (repo convention).
"""

import re
import uuid

from lumirss.adapters.freshrss import AdapterError
from lumirss.rsshub import RssHubInvalidParameters
from lumirss.rsshub_route_store import (
    SENSITIVE_PARAM,
    _load_params,
    _params_json,
    compute_route_key,
    mask_params,
)
from lumirss.storage import Database
from lumirss.util import utc_now

__all__ = [
    "MAX_PRESETS",
    "RssHubParamPresetStore",
    "RssHubPresetLimit",
    "RssHubPresetNotFound",
    "sensitive_keys",
]

MAX_PRESETS = 20
MAX_NAME_LENGTH = 80
_MAX_PARAM_KEY_LENGTH = 100
_MAX_PARAM_VALUE_LENGTH = 2000

_SENSITIVE_RE = re.compile(SENSITIVE_PARAM, re.IGNORECASE)


class RssHubPresetLimit(AdapterError):
    """The per-user preset cap (MAX_PRESETS) is exhausted."""


class RssHubPresetNotFound(AdapterError):
    """The referenced parameter preset does not exist for this user."""


def sensitive_keys(params: dict[str, str]) -> list[str]:
    """参数里需要重新绑定的敏感键（稳定排序；哨兵值回填必被拒）。"""
    return sorted(key for key in params if _SENSITIVE_RE.search(key))


def _validate_preset_params(route, params: dict[str, str]) -> dict[str, str]:
    """与 preview 同规则的入参校验（真实值上做，掩码前）。

    - 模板占位符参数：非空 + pattern 全匹配（与 build_path 一致）；
    - 其余键按 query 参数对待：非空键、有界长度、无控制字符。
    """
    clean: dict[str, str] = {}
    template_keys = {parameter.key: parameter for parameter in route.parameters}
    for key, value in params.items():
        if not isinstance(key, str) or not key.strip():
            raise RssHubInvalidParameters("Parameter keys must be non-empty.")
        if not isinstance(value, str):
            raise RssHubInvalidParameters(
                f"Parameter '{key}' must be a string."
            )
        if any(ord(char) < 32 for char in key + value):
            raise RssHubInvalidParameters(
                f"Parameter '{key}' must not contain control characters."
            )
        if len(key) > _MAX_PARAM_KEY_LENGTH or len(value) > _MAX_PARAM_VALUE_LENGTH:
            raise RssHubInvalidParameters(f"Parameter '{key}' is too long.")
        parameter = template_keys.get(key)
        if parameter is not None:
            if not value.strip():
                raise RssHubInvalidParameters(
                    f"Missing RSSHub route parameter '{parameter.key}'."
                )
            if not re.fullmatch(parameter.pattern, value):
                raise RssHubInvalidParameters(
                    f"RSSHub route parameter '{parameter.key}' is invalid."
                )
        clean[key] = value
    return clean


class RssHubParamPresetStore:
    """参数方案 CRUD（每用户库内；cap + 哨兵化都在 store 层保证）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self, *, template_id: str, params: dict[str, str], name: str
    ) -> dict[str, object]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM rsshub_param_presets", ()
        )
        if row is not None and int(row["n"]) >= MAX_PRESETS:
            raise RssHubPresetLimit(
                f"Too many parameter presets (max {MAX_PRESETS})."
            )
        has_sensitive = any(
            _SENSITIVE_RE.search(key) and value.strip()
            for key, value in params.items()
        )
        route_key = compute_route_key(template_id, params)
        preset_id = uuid.uuid4().hex
        now = utc_now()
        await self._db.execute(
            "INSERT INTO rsshub_param_presets (id, route_key, template_id, name, params_json, has_sensitive, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                preset_id,
                route_key,
                template_id,
                name,
                _params_json(params),
                1 if has_sensitive else 0,
                now,
            ),
        )
        return self._row(
            id=preset_id,
            route_key=route_key,
            template_id=template_id,
            name=name,
            params=params,
            has_sensitive=has_sensitive,
            created_at=now,
        )

    async def list_presets(self) -> list[dict[str, object]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, route_key, template_id, name, params_json, has_sensitive, created_at "
            "FROM rsshub_param_presets ORDER BY created_at DESC, id"
        )
        return [
            self._row(
                id=str(row["id"]),
                route_key=str(row["route_key"]),
                template_id=str(row["template_id"]),
                name=str(row["name"]),
                params=_load_params(row["params_json"]),
                has_sensitive=bool(row["has_sensitive"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    async def delete(self, preset_id: str) -> bool:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id FROM rsshub_param_presets WHERE id = ?", (preset_id,)
        )
        if row is None:
            return False
        await self._db.execute(
            "DELETE FROM rsshub_param_presets WHERE id = ?", (preset_id,)
        )
        return True

    async def apply(self, preset_id: str) -> dict[str, object]:
        """回填数据（纯只读）：敏感键以 '***' 哨兵返回 + 需重新绑定标记。

        服务端从不存储敏感真实值——requiresRebind=True 时客户端必须让
        用户重输 sensitiveKeys 里的键后才能发起预览。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, route_key, template_id, name, params_json, has_sensitive, created_at "
            "FROM rsshub_param_presets WHERE id = ?",
            (preset_id,),
        )
        if row is None:
            raise RssHubPresetNotFound("Parameter preset not found.")
        params = _load_params(row["params_json"])
        has_sensitive = bool(row["has_sensitive"])
        return {
            **self._row(
                id=str(row["id"]),
                route_key=str(row["route_key"]),
                template_id=str(row["template_id"]),
                name=str(row["name"]),
                params=params,
                has_sensitive=has_sensitive,
                created_at=str(row["created_at"]),
            ),
            "requiresRebind": has_sensitive,
            "sensitiveKeys": sensitive_keys(params),
        }

    @staticmethod
    def _row(
        *,
        id: str,  # noqa: A002 — 与列名对齐的内部形状
        route_key: str,
        template_id: str,
        name: str,
        params: dict[str, str],
        has_sensitive: bool,
        created_at: str,
    ) -> dict[str, object]:
        return {
            "id": id,
            "routeKey": route_key,
            "templateId": template_id,
            "name": name,
            "params": mask_params(params),
            "hasSensitive": has_sensitive,
            "createdAt": created_at,
        }
