"""N021/N025 路由收藏、最近使用与运行时间线 —— Lumi 自有元数据。

All tables are per-user (migrations 0071/0072 land in every user's
SQLite file via the routing database). Two security properties hold by
construction:

- 参数只存脱敏值：``mask_params`` 用与 Web F047 相同的敏感键规则
  （token/key/secret/sign/code/password）把敏感参数值替换为 ``***``
  哨兵，原始值既不进 route_key 也不进 params_json——收藏/最近使用
  行里没有任何凭据可泄。
- ``record_run`` 每次插入后按 route_key 裁剪到最近 20 条（N025 上限）。

SQL stays an inline literal at each execute site (repo convention).
"""

import json
import re
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

__all__ = [
    "SENSITIVE_PARAM",
    "RssHubRouteStore",
    "compute_route_key",
    "mask_params",
]

# 与 Web 端 F047 SENSITIVE_QUERY 同一规则（lib/rsshub-params.ts）。
SENSITIVE_PARAM = "token|key|secret|sign|code|password"

# N025：每个 route_key 只保留最近 N 条运行记录（插入时裁剪）。
MAX_RUNS_PER_ROUTE = 20

_SENSITIVE_MARKER = "***"

_SENSITIVE_RE = re.compile(SENSITIVE_PARAM, re.IGNORECASE)


def mask_params(params: dict[str, str]) -> dict[str, str]:
    """敏感参数值 → '***' 哨兵；其余原样（值本身已受 pattern 约束）。"""
    return {
        key: (_SENSITIVE_MARKER if _SENSITIVE_RE.search(key) else value)
        for key, value in params.items()
    }


def compute_route_key(template_id: str, params: dict[str, str]) -> str:
    """模板 id + 参数签名（脱敏后、键序稳定）→ 跨设备稳定的存储键。"""
    masked = mask_params(params)
    signature = "&".join(f"{key}={masked[key]}" for key in sorted(masked))
    return f"{template_id}|{signature}" if signature else template_id


def _params_json(params: dict[str, str]) -> str:
    return json.dumps(mask_params(params), ensure_ascii=False, sort_keys=True)


def _load_params(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(loaded, dict):
        return {}
    return {str(k): str(v) for k, v in loaded.items()}


class RssHubRouteStore:
    """收藏 / 最近使用 / 运行时间线（全部每用户库内）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ---- favorites (N021) -------------------------------------------------

    async def put_favorite(
        self,
        *,
        template_id: str,
        params: dict[str, str],
        label: str = "",
    ) -> dict[str, Any]:
        route_key = compute_route_key(template_id, params)
        now = utc_now()
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO rsshub_route_favorites (route_key, template_id, label, params_json, created_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(route_key) DO UPDATE SET label = excluded.label, template_id = excluded.template_id, params_json = excluded.params_json",
            (route_key, template_id, label, _params_json(params), now),
        )
        return self._favorite_row(route_key, template_id, label, params, now)

    async def delete_favorite(self, route_key: str) -> bool:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT route_key FROM rsshub_route_favorites WHERE route_key = ?",
            (route_key,),
        )
        if row is None:
            return False
        await self._db.execute(
            "DELETE FROM rsshub_route_favorites WHERE route_key = ?",
            (route_key,),
        )
        return True

    async def list_favorites(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT route_key, template_id, label, params_json, created_at FROM rsshub_route_favorites ORDER BY created_at DESC, route_key"
        )
        return [
            self._favorite_row(
                str(row["route_key"]),
                str(row["template_id"]),
                str(row["label"] or ""),
                _load_params(row["params_json"]),
                str(row["created_at"]),
            )
            for row in rows
        ]

    @staticmethod
    def _favorite_row(
        route_key: str,
        template_id: str,
        label: str,
        params: dict[str, str],
        created_at: str,
    ) -> dict[str, Any]:
        return {
            "routeKey": route_key,
            "templateId": template_id,
            "label": label,
            "params": mask_params(params),
            "createdAt": created_at,
        }

    # ---- recent (N021) ----------------------------------------------------

    async def record_recent(
        self,
        *,
        template_id: str,
        params: dict[str, str],
        success: bool,
    ) -> None:
        """成功一次 preview/subscribe 才调用（失败不记录——由调用方保证）。"""
        route_key = compute_route_key(template_id, params)
        now = utc_now()
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO rsshub_route_recent (route_key, template_id, params_json, last_used_at, last_success_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(route_key) DO UPDATE SET "
            "template_id = excluded.template_id, params_json = excluded.params_json, "
            "last_used_at = excluded.last_used_at, "
            "last_success_at = COALESCE(excluded.last_success_at, rsshub_route_recent.last_success_at)",
            (
                route_key,
                template_id,
                _params_json(params),
                now,
                now if success else None,
            ),
        )

    async def list_recent(self, *, limit: int = 10) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT route_key, template_id, params_json, last_used_at, last_success_at FROM rsshub_route_recent "
            "ORDER BY last_used_at DESC, route_key LIMIT ?",
            (max(1, min(limit, 50)),),
        )
        return [
            {
                "routeKey": str(row["route_key"]),
                "templateId": str(row["template_id"]),
                "params": mask_params(_load_params(row["params_json"])),
                "lastUsedAt": str(row["last_used_at"]),
                "lastSuccessAt": (
                    str(row["last_success_at"]) if row["last_success_at"] else None
                ),
            }
            for row in rows
        ]

    # ---- runs (N025) ------------------------------------------------------

    async def record_run(
        self,
        *,
        route_key: str,
        status: str,
        duration_ms: int,
        entry_count: int | None,
        failure_class: str | None,
    ) -> None:
        """写入一次运行并裁剪到每 route_key 最近 MAX_RUNS_PER_ROUTE 条。"""
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO rsshub_route_runs (route_key, ran_at, status, duration_ms, entry_count, failure_class) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (route_key, utc_now(), status, duration_ms, entry_count, failure_class),
        )
        await self._db.execute(
            "DELETE FROM rsshub_route_runs WHERE route_key = ? AND id NOT IN ("
            "SELECT id FROM rsshub_route_runs WHERE route_key = ? ORDER BY id DESC LIMIT ?"
            ")",
            (route_key, route_key, MAX_RUNS_PER_ROUTE),
        )

    async def list_runs(
        self, route_key: str, *, limit: int = MAX_RUNS_PER_ROUTE
    ) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, route_key, ran_at, status, duration_ms, entry_count, failure_class FROM rsshub_route_runs "
            "WHERE route_key = ? ORDER BY id DESC LIMIT ?",
            (route_key, max(1, min(limit, MAX_RUNS_PER_ROUTE))),
        )
        return [
            {
                "id": int(row["id"]),
                "routeKey": str(row["route_key"]),
                "ranAt": str(row["ran_at"]),
                "status": str(row["status"]),
                "durationMs": int(row["duration_ms"]),
                "entryCount": (
                    int(row["entry_count"]) if row["entry_count"] is not None else None
                ),
                "failureClass": (
                    str(row["failure_class"]) if row["failure_class"] else None
                ),
            }
            for row in rows
        ]

    async def last_success_with_entries(
        self, route_key: str, *, since_iso: str
    ) -> bool:
        """窗口内是否存在 entry_count > 0 的成功运行（N026 no_new_content 判定）。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id FROM rsshub_route_runs WHERE route_key = ? AND status = 'ok' "
            "AND entry_count IS NOT NULL AND entry_count > 0 AND ran_at >= ? LIMIT 1",
            (route_key, since_iso),
        )
        return row is not None
