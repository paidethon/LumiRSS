"""NEW-375 配额变更批次 —— 一组账户的额度变更：预览 → 确认 → 逐账户结果。

- **预览**（POST preview）：持久化一份 draft（status=draft，不改任何
  账户）。每个目标账户给出：现有 caps（user_quotas 真实行）→ 拟变
  更值 → **超额影响**：该账户当日 AI 已用次数（其 per-user 库的
  ai_usage 日窗口键，计数而已）与新上限的差 → 预计被拒次数下限。
  账户不存在 → skipped + 原因，预览如实分账；
- **执行**（POST execute，step-up quota_batch_execute）：逐账户走
  UserQuotaStore.set_caps / clear_caps（与单人设置同一执行点），
  单账户失败不中断批次，结果逐账户落账（ok/skipped/error）；
  批次状态机 draft → executed | cancelled，set 语义，行永不删除；
- 无任何绕过单人校验的捷径：复用 _normalize_caps 的全部边界。

测试用 `datetime.now(UTC) - timedelta` 造时间，无固定日历日期。
"""

import json
import uuid
from typing import Any

from lumirss.db_tx import transaction
from lumirss.user_quotas import UserQuotaStore
from lumirss.util import utc_now

MAX_BATCH_ACCOUNTS = 50


class QuotaBatchInvalid(ValueError):
    """批次载荷非法（422）。"""


class QuotaBatchNotFound(Exception):
    """批次不存在（404）。"""


class QuotaBatchStateInvalid(Exception):
    """批次状态不允许该操作（409）。"""


def _clean_change_item(raw: Any, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise QuotaBatchInvalid(f"changes[{index}] 必须是对象。")
    user_id = raw.get("userId")
    if not isinstance(user_id, str) or not user_id.strip():
        raise QuotaBatchInvalid(f"changes[{index}].userId 必须是非空字符串。")
    clear = bool(raw.get("clear", False))
    caps = raw.get("caps")
    if clear and caps:
        raise QuotaBatchInvalid(f"changes[{index}] 不能同时 clear 与 caps。")
    clean_caps: dict[str, int] = {}
    if not clear:
        if not isinstance(caps, dict) or not caps:
            raise QuotaBatchInvalid(f"changes[{index}].caps 必须是非空对象（或声明 clear）。")
        # 复用单人设置的完整校验边界（未知键/越界一律拒绝），
        # 并归一为批次的稳定 422（不让 QuotaPolicyError 变 500）。
        from lumirss.user_quotas import QuotaPolicyError, _normalize_caps

        try:
            clean_caps = _normalize_caps(caps)
        except QuotaPolicyError as exc:
            raise QuotaBatchInvalid(str(exc)) from exc
    return {"userId": user_id.strip(), "clear": clear, "caps": clean_caps}


def clean_changes(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise QuotaBatchInvalid("changes 必须是非空数组。")
    if len(raw) > MAX_BATCH_ACCOUNTS:
        raise QuotaBatchInvalid(f"一批最多 {MAX_BATCH_ACCOUNTS} 个账户。")
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        clean = _clean_change_item(item, index)
        if clean["userId"] in seen:
            raise QuotaBatchInvalid(f"changes[{index}] 重复账户：{clean['userId']}。")
        seen.add(clean["userId"])
        items.append(clean)
    return items


async def _ai_usage_today_for(state: Any, user_id: str) -> int | None:
    """目标账户当日 AI 已用次数（其 per-user 库；计数，无内容）。"""
    from lumirss.new374_resource_bill import open_user_db

    try:
        db = await open_user_db(state, user_id)
        from lumirss.ai_quota import window_bounds

        bounds = window_bounds(window="day")
        row = await db.fetch_one(
            "SELECT calls FROM ai_usage WHERE window_key = ?", (bounds.key,)
        )
        return int(row["calls"]) if row is not None else 0
    except Exception:  # noqa: BLE001 — 打不开的账户如实「未知」
        return None


async def preview_change(state: Any, control_db: Any, change: dict[str, Any]) -> dict[str, Any]:
    user_id = str(change["userId"])
    accounts = None
    from lumirss.accounts_store import AccountsStore

    accounts = AccountsStore(control_db)
    user = await accounts.get_user(user_id)
    if user is None:
        return {
            "userId": user_id,
            "outcome": "skipped",
            "reason": "账户不存在。",
            "currentCaps": None,
            "proposed": None,
            "overQuotaImpact": None,
        }
    store = UserQuotaStore(control_db)
    current_caps = await store.caps_for(user_id)
    proposed = {} if change["clear"] else dict(change["caps"])
    used = await _ai_usage_today_for(state, user_id)
    impact: dict[str, Any] | None = None
    new_ai_cap = proposed.get("aiQuotaPerDay")
    if new_ai_cap is not None and used is not None:
        impact = {
            "aiCallsToday": used,
            "newDailyCap": int(new_ai_cap),
            "projectedDeniedMin": max(0, used - int(new_ai_cap)),
            "note": "按当日已用次数下限估计；已有超额用量不会被追溯回收。",
        }
    return {
        "userId": user_id,
        "username": str(user["username"]) if user.get("username") else None,
        "outcome": "preview",
        "currentCaps": current_caps,
        "proposed": proposed if proposed else None,
        "clear": bool(change["clear"]),
        "overQuotaImpact": impact,
    }


async def create_draft(
    control_db: Any, *, changes: list[dict[str, Any]], by: str
) -> dict[str, Any]:
    await control_db.migrate()
    batch_id = uuid.uuid4().hex
    await control_db.execute(
        "INSERT INTO admin_quota_batches (id, status, change, created_by, created_at)"
        " VALUES (?, 'draft', ?, ?, ?)",
        (batch_id, json.dumps(changes, ensure_ascii=False), by, utc_now()),
    )
    return {"batchId": batch_id, "status": "draft", "count": len(changes)}


async def get_batch(control_db: Any, batch_id: str) -> dict[str, Any] | None:
    await control_db.migrate()
    row = await control_db.fetch_one(
        "SELECT * FROM admin_quota_batches WHERE id = ?", (batch_id,)
    )
    if row is None:
        return None
    results = await control_db.fetch_all(
        "SELECT user_id, outcome, before_json, after_json, detail FROM admin_quota_batch_results"
        " WHERE batch_id = ? ORDER BY id ASC",
        (batch_id,),
    )
    return {
        "batchId": str(row["id"]),
        "status": str(row["status"]),
        "change": json.loads(str(row["change"])),
        "createdBy": str(row["created_by"]),
        "createdAt": str(row["created_at"]),
        "executedAt": row["executed_at"],
        "executedBy": row["executed_by"],
        "results": [
            {
                "userId": str(r["user_id"]),
                "outcome": str(r["outcome"]),
                "before": json.loads(str(r["before_json"])) if r["before_json"] else None,
                "after": json.loads(str(r["after_json"])) if r["after_json"] else None,
                "detail": r["detail"],
            }
            for r in results
        ],
    }


async def cancel_batch(control_db: Any, batch_id: str) -> dict[str, Any]:
    await control_db.migrate()

    def _write(conn: Any) -> dict[str, Any]:
        row = conn.execute(
            "SELECT status FROM admin_quota_batches WHERE id = ?", (batch_id,)
        ).fetchone()
        if row is None:
            raise QuotaBatchNotFound(batch_id)
        if str(row["status"]) != "draft":
            raise QuotaBatchStateInvalid(batch_id)
        conn.execute(
            "UPDATE admin_quota_batches SET status = 'cancelled' WHERE id = ?", (batch_id,)
        )
        return {"batchId": batch_id, "status": "cancelled"}

    return await transaction(control_db, _write)


async def execute_batch(
    state: Any, control_db: Any, *, batch_id: str, by: str
) -> dict[str, Any]:
    """逐账户执行；单账户失败隔离为 error 行，绝不中断批次。

    FIX-225：取消不是只改数据库标签——每个账户发起前 re-check 批次
    状态，并发取消后 worker 停止可取消工作（不再对后续账户写入）；
    已执行账户的结果行照常落账（诚实呈现）；终态迁移带
    ``status = 'draft'`` 守卫，绝不把已取消的批次复活成 executed，
    并以 ``stoppedReason`` 如实上报。"""
    await control_db.migrate()
    batch = await get_batch(control_db, batch_id)
    if batch is None:
        raise QuotaBatchNotFound(batch_id)
    if batch["status"] != "draft":
        raise QuotaBatchStateInvalid(batch_id)

    store = UserQuotaStore(control_db)
    from lumirss.accounts_store import AccountsStore

    accounts = AccountsStore(control_db)
    outcomes: list[dict[str, Any]] = []
    stopped_reason: str | None = None
    for change in batch["change"]:
        # FIX-225：发起前 re-check——并发取消的批次停止执行。
        status_row = await control_db.fetch_one(
            "SELECT status FROM admin_quota_batches WHERE id = ?", (batch_id,)
        )
        if status_row is not None and str(status_row["status"]) != "draft":
            stopped_reason = "cancelled"
            break
        user_id = str(change["userId"])
        before = await store.caps_for(user_id)
        user = await accounts.get_user(user_id)
        if user is None:
            outcomes.append(
                {"userId": user_id, "outcome": "skipped", "before": before, "after": None, "detail": "账户不存在。"}
            )
            continue
        try:
            if change["clear"]:
                await store.clear_caps(user_id=user_id, updated_by=by)
                after: dict[str, int] | None = None
            else:
                after = await store.set_caps(
                    user_id=user_id, caps=change["caps"], updated_by=by
                )
            outcomes.append(
                {"userId": user_id, "outcome": "ok", "before": before, "after": after, "detail": None}
            )
        except Exception as exc:  # noqa: BLE001 — 单账户失败不中断批次
            outcomes.append(
                {"userId": user_id, "outcome": "error", "before": before, "after": None, "detail": str(exc)[:200]}
            )

    def _write(conn: Any) -> dict[str, Any]:
        # FIX-225：终态迁移带 draft 守卫——取消落定的批次保持 cancelled。
        conn.execute(
            "UPDATE admin_quota_batches SET status = 'executed', executed_at = ?, executed_by = ? WHERE id = ? AND status = 'draft'",
            (utc_now(), by, batch_id),
        )
        for item in outcomes:
            conn.execute(
                "INSERT INTO admin_quota_batch_results (batch_id, user_id, outcome, before_json, after_json, detail)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    batch_id,
                    item["userId"],
                    item["outcome"],
                    json.dumps(item["before"], ensure_ascii=False) if item["before"] is not None else None,
                    json.dumps(item["after"], ensure_ascii=False) if item["after"] is not None else None,
                    item["detail"],
                ),
            )
        row = conn.execute(
            "SELECT status FROM admin_quota_batches WHERE id = ?", (batch_id,)
        ).fetchone()
        status = str(row["status"]) if row is not None else "executed"
        return {"batchId": batch_id, "status": status, "results": outcomes}

    result = await transaction(control_db, _write)
    if stopped_reason is not None:
        result["stoppedReason"] = stopped_reason
    return result


async def list_batches(control_db: Any, limit: int = 20) -> list[dict[str, Any]]:
    await control_db.migrate()
    rows = await control_db.fetch_all(
        "SELECT id, status, created_at, executed_at FROM admin_quota_batches"
        " ORDER BY created_at DESC, id DESC LIMIT ?",
        (max(1, min(limit, 50)),),
    )
    return [
        {
            "batchId": str(row["id"]),
            "status": str(row["status"]),
            "createdAt": str(row["created_at"]),
            "executedAt": row["executed_at"],
        }
        for row in rows
    ]
