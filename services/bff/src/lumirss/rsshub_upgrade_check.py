"""N028 路由升级兼容检查 — 管理员级、预升级、有界的路由健康基线。

诚实范围（文档化于端点 docstring，测试固定）：

- **只探测当前运行实例**。Lumi 没有 Docker 视角（架构红线：永不挂
  Docker socket），无法验证「目标镜像已生效」——targetImage 恒为
  pending，逐路由状态锚定到 checkedImage（目录快照生成时所在的固定
  镜像 sha，唯一可引用的镜像证据）。
- **只覆盖管理员本人用户库可见的路由键**：订阅 URL 反推
  （match_route_path）+ 本人的收藏/最近使用（脱敏 route_key）。
  跨用户聚合每用户库太贵且非升级检查所必需——成员的路由不受此检查。
- **有界**：单次最多 MAX_CHECK_ROUTES 条路由被探测（其余如实记为
  skipped/check_budget_exceeded），每条探测走既有 preview 的有界抓取
  （超时 + 2MiB body 上限 + 域内重定向），顺序执行不放大并发。
- **keep-old = 默认**：本模块只写报告行，绝不触发任何镜像/容器操作。
"""

import json
from pathlib import Path

from lumirss.feed_preview import FeedTooLarge, NotAFeedError
from lumirss.rsshub import (
    FAILURE_BAD_CONTENT,
    RssHubFetchError,
    RssHubRouteNotFound,
)
from lumirss.rsshub_route_store import RssHubRouteStore, parse_route_key
from lumirss.storage import Database
from lumirss.util import utc_now

__all__ = [
    "MAX_CHECK_REPORTS",
    "MAX_CHECK_ROUTES",
    "RssHubUpgradeCheckStore",
    "pinned_image",
]

MAX_CHECK_ROUTES = 12
MAX_CHECK_REPORTS = 3

_ROUTES_SNAPSHOT_PATH = (
    Path(__file__).resolve().parent / "rsshub_routes.generated.json"
)

# 状态（routes_json 内）：
SKIPPED = "skipped"
OK = "ok"
FAILED = "failed"


def pinned_image() -> str | None:
    """目录快照的固定镜像（_meta.rsshubImage）；快照缺失 → None（诚实）。"""
    try:
        meta = json.loads(_ROUTES_SNAPSHOT_PATH.read_text(encoding="utf-8"))[
            "_meta"
        ]
    except (OSError, ValueError, KeyError):
        return None
    image = meta.get("rsshubImage")
    return image if isinstance(image, str) and image else None


class RssHubUpgradeCheckStore:
    """检查报告（keep-last-3；存管理员自己的用户库）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def save(
        self,
        *,
        target_image: str | None,
        checked_image: str | None,
        routes: list[dict[str, object]],
    ) -> dict[str, object]:
        await self._db.migrate()
        ok_count = sum(1 for route in routes if route["status"] == OK)
        failed_count = sum(1 for route in routes if route["status"] == FAILED)
        skipped_count = sum(
            1 for route in routes if route["status"] == SKIPPED
        )
        await self._db.execute(
            "INSERT INTO rsshub_upgrade_checks (ran_at, target_image, checked_image, route_count, ok_count, failed_count, skipped_count, routes_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                utc_now(),
                target_image,
                checked_image,
                len(routes),
                ok_count,
                failed_count,
                skipped_count,
                json.dumps(routes, ensure_ascii=False, sort_keys=True),
            ),
        )
        # keep-last-3：老报告即刻清理（同一次写入内，绝不无限增长）。
        await self._db.execute(
            "DELETE FROM rsshub_upgrade_checks WHERE id NOT IN ("
            "SELECT id FROM rsshub_upgrade_checks ORDER BY id DESC LIMIT ?"
            ")",
            (MAX_CHECK_REPORTS,),
        )
        return await self._latest()

    async def list_reports(self) -> list[dict[str, object]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, ran_at, target_image, checked_image, route_count, ok_count, failed_count, skipped_count, routes_json "
            "FROM rsshub_upgrade_checks ORDER BY id DESC LIMIT ?",
            (MAX_CHECK_REPORTS,),
        )
        return [self._row(row) for row in rows]

    async def _latest(self) -> dict[str, object]:
        row = await self._db.fetch_one(
            "SELECT id, ran_at, target_image, checked_image, route_count, ok_count, failed_count, skipped_count, routes_json "
            "FROM rsshub_upgrade_checks ORDER BY id DESC LIMIT 1",
            (),
        )
        assert row is not None  # 刚插入即读，必然存在
        return self._row(row)

    @staticmethod
    def _row(row) -> dict[str, object]:
        try:
            routes = json.loads(row["routes_json"])
        except ValueError:
            routes = []
        if not isinstance(routes, list):
            routes = []
        return {
            "id": int(row["id"]),
            "ranAt": str(row["ran_at"]),
            "targetImage": (
                str(row["target_image"]) if row["target_image"] else None
            ),
            "targetStatus": "pending" if row["target_image"] else None,
            "checkedImage": (
                str(row["checked_image"]) if row["checked_image"] else None
            ),
            "routeCount": int(row["route_count"]),
            "okCount": int(row["ok_count"]),
            "failedCount": int(row["failed_count"]),
            "skippedCount": int(row["skipped_count"]),
            "routes": routes,
        }


async def collect_route_keys(
    request, *, store: RssHubRouteStore
) -> list[tuple[str, str]]:
    """收集管理员本人可见的路由键 + 来源标记（订阅 > 收藏 > 最近）。

    订阅 URL 反推给出**真实参数**（FreshRSS 订阅列表是唯一真源）；
    收藏/最近使用给出**脱敏参数**（哨兵）。同 route_key 去重，订阅
    来源优先（可完整重建探测 URL）。"""
    import urllib.parse

    from lumirss.deps import _get_control_adapter
    from lumirss.rsshub import match_route_path
    from lumirss.rsshub_route_store import compute_route_key

    collected: dict[str, str] = {}

    control = _get_control_adapter(request)
    for subscription in await control.list_subscriptions():
        path = urllib.parse.urlsplit(subscription.feed_url).path
        matched = match_route_path(path)
        if matched is None:
            continue
        route, params = matched
        route_key = compute_route_key(route.id, params)
        collected.setdefault(route_key, "subscription")

    for favorite in await store.list_favorites():
        collected.setdefault(str(favorite["routeKey"]), "favorite")
    for recent in await store.list_recent():
        collected.setdefault(str(recent["routeKey"]), "recent")

    return list(collected.items())


async def run_upgrade_check(
    request, *, target_image: str | None
) -> dict[str, object]:
    """执行一次检查：采集 → 有界探测 → 落报告（keep-last-3）。

    探测复用路由 preview 的注入缝（app.state.rsshub_route_probe），
    测试与故障注入语义与 N026 完全一致。"""
    store = RssHubRouteStore(request.app.state.db)
    check_store = RssHubUpgradeCheckStore(request.app.state.db)
    entries = await collect_route_keys(request, store=store)

    routes: list[dict[str, object]] = []
    for route_key, origin in entries[:MAX_CHECK_ROUTES]:
        routes.append(
            await _probe_one(request, route_key, origin)
        )
    for route_key, origin in entries[MAX_CHECK_ROUTES:]:
        # 有界承诺：超出预算的路由诚实记 skipped，绝不静默丢弃。
        routes.append(
            {
                "routeKey": route_key,
                "status": SKIPPED,
                "entryCount": None,
                "failureClass": "check_budget_exceeded",
                "origin": origin,
            }
        )
    return await check_store.save(
        target_image=target_image,
        checked_image=pinned_image(),
        routes=routes,
    )


async def _probe_one(request, route_key: str, origin: str) -> dict[str, object]:
    """单路由探测：可重建 → 真实 preview；否则诚实 skipped。"""
    parsed = parse_route_key(route_key)
    if parsed is None:
        return {
            "routeKey": route_key,
            "status": SKIPPED,
            "entryCount": None,
            "failureClass": "malformed_route_key",
            "origin": origin,
        }
    template_id, params = parsed
    from lumirss.routers.rsshub import _catalog_route, _do_preview

    try:
        _catalog_route(template_id)
    except RssHubRouteNotFound:
        return {
            "routeKey": route_key,
            "status": SKIPPED,
            "entryCount": None,
            "failureClass": "route_not_in_catalog",
            "origin": origin,
        }
    if any(value == "***" for value in params.values()):
        # 敏感值从未存储——无法重建探测 URL；这是哨兵语义的诚实延续。
        return {
            "routeKey": route_key,
            "status": SKIPPED,
            "entryCount": None,
            "failureClass": "sensitive_params_unavailable",
            "origin": origin,
        }
    try:
        preview = await _do_preview(
            request, template_id, params, base_override=None
        )
    except (RssHubFetchError, NotAFeedError, FeedTooLarge) as exc:
        failure_class = getattr(exc, "failure_class", None)
        if failure_class is None and isinstance(
            exc, (NotAFeedError, FeedTooLarge)
        ):
            failure_class = FAILURE_BAD_CONTENT
        return {
            "routeKey": route_key,
            "status": FAILED,
            "entryCount": None,
            "failureClass": failure_class,
            "origin": origin,
        }
    return {
        "routeKey": route_key,
        "status": OK,
        "entryCount": preview.entry_count,
        "failureClass": None,
        "origin": origin,
    }
