"""NEW-377 后台任务阻塞定位 —— 等的是配额、限流、锁还是依赖失败。

四类阻塞各来自**真实信号**，每次诊断重算（不拿旧账下结论）：

- **quota**：账户当日 AI 已用次数 ≥ 管理员日上限（user_quotas 行），
  或接入配额来源的 pending 积压（api_intake_counts.pending > 0）；
  只有计数与账户 id，绝无内容；
- **rate_limit**：来源刷新日志（source_refresh_log）近 24h 的
  error 计数（按结果类汇总；来源 URL 是订阅配置细节，跨账户视图
  只给计数，不给 URL）；
- **lock**：runtime_leases 中未过期租约（scope 只取前缀类别，如
  ``digest`` / ``gpt-digest``——scope 全串无内容但也无必要）；
  处置 = 等过期（expiresAt 展示）。**没有强制解锁入口**——存活
  租约可抢占会制造双写，这是 ARCH-08 的正确性前提，不是能力缺失；
- **dependency**：FreshRSS 未绑定的账户计数 + 部署状态文件缺失/
  不可读（deploy_status 的诚实原因原文）。

每次诊断把观测落账（admin_task_blockers，保最近 200 行）；响应中
每类阻塞给出 ``safeAction`` 指针——只指向既有安全治理面（NEW-371
暂停 / NEW-375 配额批次 / 部署状态查看），绝不指向 shell。
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from lumirss.util import utc_now

_LEDGER_KEEP = 200
_RATE_WINDOW_HOURS = 24

SAFE_ACTIONS: dict[str, dict[str, str]] = {
    "quota": (
        "用 NEW-375 配额批次预览并调整上限，或用 NEW-371 暂停对应任务档。"
    ),
    "rate_limit": (
        "查看对应账户的来源新鲜度/手动健康检查（成员自己 surfaces）；"
        "实例级可暂停受影响的任务档（NEW-371）。"
    ),
    "lock": (
        "等待租约过期（见 expiresAt）；无强制解锁入口——抢占存活租约会"
        "制造双写。持续不释放请连同 expiresAt 报告给运维。"
    ),
    "dependency": (
        "查看部署状态（GET /api/v1/admin/deploy-status）与系统面板；"
        "绑定修复属于账户本人的 FreshRSS 绑定流程。"
    ),
}


async def _per_user_signals(state: Any, control_db: Any, limit: int) -> dict[str, Any]:
    """逐活跃账户收集计数类信号（小规模实例；单账户失败隔离跳过）。"""
    from lumirss.accounts_store import AccountsStore
    from lumirss.storage import Database
    from lumirss.user_quotas import UserQuotaStore
    from lumirss.user_scope import RoutingDatabase

    quota_blocked: list[dict[str, Any]] = []
    intake_pending: list[dict[str, Any]] = []
    rate_error_counts: list[dict[str, Any]] = []
    locks: list[dict[str, Any]] = []
    unbound: list[str] = []

    accounts = AccountsStore(control_db)
    routing = state.db
    is_routing = isinstance(routing, RoutingDatabase)
    try:
        user_ids = await accounts.active_user_ids()
    except Exception:  # noqa: BLE001 — control 库不可用时如实全空
        return {
            "quotaBlocked": [],
            "intakePending": [],
            "rateErrorCounts": [],
            "locks": [],
            "unboundAccounts": [],
            "accountErrors": 1,
        }

    account_errors = 0
    for user_id in user_ids[: max(1, limit)]:
        try:
            # 管理员日上限（control 库）。
            caps = await UserQuotaStore(control_db).caps_for(user_id)
            target: Database = (
                Database(routing.user_db_path(user_id)) if is_routing else routing
            )
            await target.migrate()

            used = None
            try:
                from lumirss.ai_quota import window_bounds

                bounds = window_bounds(window="day")
                row = await target.fetch_one(
                    "SELECT calls FROM ai_usage WHERE window_key = ?", (bounds.key,)
                )
                used = int(row["calls"]) if row is not None else 0
            except Exception:  # noqa: BLE001
                used = None
            cap = caps.get("aiQuotaPerDay")
            if used is not None and cap is not None and used >= cap:
                quota_blocked.append(
                    {"userId": user_id, "aiCallsToday": used, "dailyCap": int(cap)}
                )

            try:
                row = await target.fetch_one(
                    "SELECT COALESCE(SUM(pending), 0) AS p FROM api_intake_counts WHERE day_key = ?",
                    ((datetime.now().astimezone()).strftime("%Y-%m-%d"),),
                )
                pending = int(row["p"]) if row is not None else 0
                if pending > 0:
                    intake_pending.append({"userId": user_id, "pending": pending})
            except Exception:  # noqa: BLE001 — 表缺失 = 无接入配额
                pass

            try:
                cutoff = (datetime.now(UTC) - timedelta(hours=_RATE_WINDOW_HOURS)).isoformat(
                    timespec="seconds"
                )
                row = await target.fetch_one(
                    "SELECT COUNT(*) AS n FROM source_refresh_log"
                    " WHERE result = 'error' AND checked_at >= ?",
                    (cutoff,),
                )
                errors = int(row["n"]) if row is not None else 0
                if errors > 0:
                    rate_error_counts.append({"userId": user_id, "errorProbes": errors})
            except Exception:  # noqa: BLE001
                pass

            try:
                now = utc_now()
                rows = await target.fetch_all(
                    "SELECT scope, expires_at FROM runtime_leases WHERE expires_at > ? LIMIT 20",
                    (now,),
                )
                for lease in rows:
                    locks.append(
                        {
                            "userId": user_id,
                            "scopeKind": str(lease["scope"]).split(":", 1)[0],
                            "expiresAt": str(lease["expires_at"]),
                        }
                    )
            except Exception:  # noqa: BLE001
                pass

            try:
                row = await target.fetch_one(
                    "SELECT id FROM freshrss_binding WHERE id = 1", ()
                )
                if row is None:
                    unbound.append(user_id)
            except Exception:  # noqa: BLE001 — 表缺失按未绑定如实计
                unbound.append(user_id)
        except Exception:  # noqa: BLE001 — 单账户诊断失败不拖垮整体
            account_errors += 1

    return {
        "quotaBlocked": quota_blocked,
        "intakePending": intake_pending,
        "rateErrorCounts": rate_error_counts,
        "locks": locks,
        "unboundAccounts": unbound,
        "accountErrors": account_errors,
    }


async def _deploy_status_view() -> dict[str, Any]:
    import os

    from lumirss.deploy_status import read_deploy_status

    view = read_deploy_status(os.environ.get("LUMIRSS_DEPLOY_STATUS_FILE", ""))
    return {
        "available": bool(view["available"]),
        "reason": view["reason"],
    }


async def diagnose(state: Any, control_db: Any, *, max_accounts: int = 50) -> dict[str, Any]:
    """实时诊断：四类阻塞 + 每类 safeAction + 落账。"""
    signals = await _per_user_signals(state, control_db, max_accounts)
    deploy = await _deploy_status_view()

    categories: dict[str, list[dict[str, Any]]] = {
        "quota": [
            {"scope": "ai_daily", **item} for item in signals["quotaBlocked"]
        ]
        + [{"scope": "intake_pending", **item} for item in signals["intakePending"]],
        "rate_limit": [
            {"scope": "source_probes", **item} for item in signals["rateErrorCounts"]
        ],
        "lock": [{"scope": "runtime_lease", **item} for item in signals["locks"]],
        "dependency": [
            {"scope": "freshrss_unbound", "count": len(signals["unboundAccounts"])}
        ]
        + (
            [{"scope": "deploy_status", "reason": deploy["reason"]}]
            if not deploy["available"] and deploy["reason"]
            else []
        ),
    }

    blockers: list[dict[str, Any]] = []
    for category, items in categories.items():
        for item in items:
            blockers.append(
                {
                    "category": category,
                    **item,
                    "safeAction": SAFE_ACTIONS[category],
                }
            )

    await control_db.migrate()
    diagnosed_at = utc_now()
    if blockers:
        await control_db.execute_many(
            "INSERT INTO admin_task_blockers (category, scope, subject, detail_json, diagnosed_at)"
            " VALUES (?, ?, ?, ?, ?)",
            [
                (
                    b["category"],
                    str(b.get("scope", "")),
                    str(b.get("userId", b.get("scope", ""))),
                    json.dumps({k: v for k, v in b.items() if k not in ("category", "safeAction")}, ensure_ascii=False),
                    diagnosed_at,
                )
                for b in blockers
            ],
        )
        # 台账有界：只留最近 _LEDGER_KEEP 行。
        await control_db.execute(
            "DELETE FROM admin_task_blockers WHERE id NOT IN"
            " (SELECT id FROM admin_task_blockers ORDER BY id DESC LIMIT ?)",
            (_LEDGER_KEEP,),
        )

    recent = await control_db.fetch_all(
        "SELECT category, scope, subject, detail_json, diagnosed_at FROM admin_task_blockers"
        " ORDER BY id DESC LIMIT 20",
        (),
    )
    return {
        "blockers": blockers,
        "counts": {key: len(items) for key, items in categories.items()},
        "safeActions": SAFE_ACTIONS,
        "accountErrors": signals["accountErrors"],
        "diagnosedAt": diagnosed_at,
        "recentLedger": [
            {
                "category": str(row["category"]),
                "scope": str(row["scope"]),
                "subject": str(row["subject"]),
                "diagnosedAt": str(row["diagnosed_at"]),
            }
            for row in recent
        ],
        "notes": [
            "诊断只含计数/键名/账户 id；无来源 URL、无文章内容、无秘密值。",
            "lock 类没有强制解锁入口（抢占存活租约会制造双写）。",
        ],
    }


async def recent_ledger(control_db: Any, limit: int = 20) -> list[dict[str, Any]]:
    await control_db.migrate()
    rows = await control_db.fetch_all(
        "SELECT category, scope, subject, diagnosed_at FROM admin_task_blockers"
        " ORDER BY id DESC LIMIT ?",
        (max(1, min(limit, 100)),),
    )
    return [
        {
            "category": str(row["category"]),
            "scope": str(row["scope"]),
            "subject": str(row["subject"]),
            "diagnosedAt": str(row["diagnosed_at"]),
        }
        for row in rows
    ]
