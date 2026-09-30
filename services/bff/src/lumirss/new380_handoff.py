"""NEW-380 运维交接摘要 —— 按真实部署与故障记录生成脱敏交接清单。

清单**逐项来自既有真实面**（NEW-371..379 + 部署状态 + schema 版本），
生成本身零网络、零 shell：

- 未完成项：open/assigned 工单（379）、active 任务暂停（371）、
  draft 配额批次（375）、draft 配置草案（376）、已排程维护窗口（373）、
  未就绪功能依赖（378 最新探测态）、近期阻塞台账（377）；
- 部署要素：schema 版本、部署状态文件（原样透传的原因文案）、
  秘密清单只有 已配置/未配置 状态位（**值永不读取、永不出现**）；
- 流转：build（存 draft，未确认）→ confirm（step-up handoff_export，
  target=操作管理员本人；确认人即对内容负责）→ export（仅 confirmed
  可导出；导出打一次 exported_at 戳 + 脱敏声明）。未确认导出 → 409。
"""

import json
import uuid
from typing import Any

from lumirss.db_tx import transaction
from lumirss.util import utc_now

# 控制库 secrets.json 的已知键（只查存在性；值绝不读取）。
_CONTROL_SECRET_KEYS = ("freshrss_pool",)


class HandoffNotFound(Exception):
    """交接摘要不存在（404）。"""


class HandoffNotConfirmed(Exception):
    """摘要未确认，不能导出（409）。"""


class HandoffStateInvalid(Exception):
    """状态不允许该操作（409）。"""


async def _task_pause_items(control_db: Any) -> list[dict[str, Any]]:
    from lumirss.new371_task_calendar import paused_task_kinds

    return [{"kind": kind} for kind in sorted(await paused_task_kinds(control_db))]


async def _ticket_items(control_db: Any) -> list[dict[str, Any]]:
    from lumirss.new379_tickets import list_tickets

    items = await list_tickets(control_db, status="open") + await list_tickets(
        control_db, status="assigned"
    )
    return [{"id": item["id"], "subject": item["subject"], "status": item["status"]} for item in items]


async def _quota_batch_items(control_db: Any) -> list[dict[str, Any]]:
    from lumirss.new375_quota_batch import list_batches

    return [
        {"batchId": item["batchId"], "status": item["status"]}
        for item in await list_batches(control_db)
        if item["status"] == "draft"
    ]


async def _config_draft_items(control_db: Any) -> list[dict[str, Any]]:
    from lumirss.new376_config_draft import list_drafts

    return [
        {"draftId": item["draftId"], "key": item["key"], "draftValue": item["draftValue"]}
        for item in await list_drafts(control_db)
        if item["status"] == "draft"
    ]


async def _maintenance_items(control_db: Any) -> list[dict[str, Any]]:
    from lumirss.new373_maintenance import list_windows

    return [
        {"id": item["id"], "title": item["title"], "startsAt": item["startsAt"], "status": item["status"]}
        for item in await list_windows(control_db)
        if item["status"] == "scheduled"
    ]


async def _dependency_gaps(control_db: Any) -> list[dict[str, Any]]:
    from lumirss.new378_feature_deps import stored_probe_state

    stored = await stored_probe_state(control_db)
    return [
        {"dep": dep, "detail": row["detail"], "probedAt": row["probedAt"]}
        for dep, row in sorted(stored.items())
        if not row["configured"]
    ]


async def _recent_blockers(control_db: Any) -> list[dict[str, Any]]:
    from lumirss.new377_task_blockers import recent_ledger

    return (await recent_ledger(control_db, limit=10))[:10]


async def _deploy_view() -> dict[str, Any]:
    import os

    from lumirss.deploy_status import read_deploy_status

    view = read_deploy_status(os.environ.get("LUMIRSS_DEPLOY_STATUS_FILE", ""))
    return {
        "available": bool(view["available"]),
        "reason": view["reason"],
        "imageTag": (view.get("deploy") or {}).get("imageTag")
        if isinstance(view.get("deploy"), dict)
        else None,
    }


def _secrets_inventory(control_secrets: Any) -> list[dict[str, Any]]:
    """控制库秘密清单：只有 已配置/未配置 状态位（值绝不读取）。"""
    inventory: list[dict[str, Any]] = []
    for key in _CONTROL_SECRET_KEYS:
        inventory.append(
            {"key": f"{key}:*", "configured": _any_prefix(control_secrets, key)}
        )
    return inventory


def _any_prefix(store: Any, prefix: str) -> bool:
    try:
        raw = store.path
        import json as _json

        data = _json.loads(raw.read_text()) if raw.exists() else {}
        return any(str(key).startswith(prefix) for key in data)
    except Exception:  # noqa: BLE001 — 读不到 = 如实未配置
        return False


async def build_summary(app_state: Any) -> dict[str, Any]:
    from lumirss.migrations import schema_version

    control_db = app_state.control_db
    await control_db.migrate()
    payload: dict[str, Any] = {
        "generatedAt": utc_now(),
        "schemaVersion": schema_version(control_db),
        "deploy": await _deploy_view(),
        "openItems": {
            "tickets": await _ticket_items(control_db),
            "taskPauses": await _task_pause_items(control_db),
            "quotaBatchesDraft": await _quota_batch_items(control_db),
            "configDrafts": await _config_draft_items(control_db),
            "maintenanceWindows": await _maintenance_items(control_db),
            "dependencyGaps": await _dependency_gaps(control_db),
            "recentBlockers": await _recent_blockers(control_db),
        },
        "secretsInventory": _secrets_inventory(app_state.control_secrets),
        "redactionNote": (
            "本清单脱敏生成：秘密只有 已配置/未配置 状态位，值永不出现；"
            "成员数据只有计数与状态，无文章内容。"
        ),
    }
    return payload


async def create_summary(app_state: Any, *, by: str) -> dict[str, Any]:
    payload = await build_summary(app_state)
    control_db = app_state.control_db
    summary_id = uuid.uuid4().hex
    await control_db.execute(
        "INSERT INTO admin_handoff_summaries (id, payload_json, confirmed, created_by, created_at)"
        " VALUES (?, ?, 0, ?, ?)",
        (summary_id, json.dumps(payload, ensure_ascii=False), by, utc_now()),
    )
    return {"summaryId": summary_id, "confirmed": False, "payload": payload}


async def get_summary(control_db: Any, summary_id: str) -> dict[str, Any] | None:
    await control_db.migrate()
    row = await control_db.fetch_one(
        "SELECT * FROM admin_handoff_summaries WHERE id = ?", (summary_id,)
    )
    if row is None:
        return None
    return {
        "summaryId": str(row["id"]),
        "confirmed": bool(row["confirmed"]),
        "exportedAt": row["exported_at"],
        "createdBy": str(row["created_by"]),
        "createdAt": str(row["created_at"]),
        "payload": json.loads(str(row["payload_json"])),
    }


async def list_summaries(control_db: Any, limit: int = 20) -> list[dict[str, Any]]:
    await control_db.migrate()
    rows = await control_db.fetch_all(
        "SELECT id, confirmed, created_by, created_at, exported_at FROM admin_handoff_summaries"
        " ORDER BY created_at DESC, id DESC LIMIT ?",
        (max(1, min(limit, 50)),),
    )
    return [
        {
            "summaryId": str(row["id"]),
            "confirmed": bool(row["confirmed"]),
            "createdBy": str(row["created_by"]),
            "createdAt": str(row["created_at"]),
            "exportedAt": row["exported_at"],
        }
        for row in rows
    ]


async def confirm_summary(control_db: Any, *, summary_id: str, by: str) -> dict[str, Any]:
    await control_db.migrate()

    def _write(conn: Any) -> dict[str, Any]:
        row = conn.execute(
            "SELECT confirmed, exported_at FROM admin_handoff_summaries WHERE id = ?",
            (summary_id,),
        ).fetchone()
        if row is None:
            raise HandoffNotFound(summary_id)
        if row["exported_at"] is not None:
            raise HandoffStateInvalid(summary_id)
        conn.execute(
            "UPDATE admin_handoff_summaries SET confirmed = 1, confirmed_by = ?, confirmed_at = ? WHERE id = ?",
            (by, utc_now(), summary_id),
        )
        return {"summaryId": summary_id, "confirmed": True}

    return await transaction(control_db, _write)


async def export_summary(control_db: Any, summary_id: str) -> dict[str, Any]:
    await control_db.migrate()
    row = await control_db.fetch_one(
        "SELECT * FROM admin_handoff_summaries WHERE id = ?", (summary_id,)
    )
    if row is None:
        raise HandoffNotFound(summary_id)
    if not row["confirmed"]:
        raise HandoffNotConfirmed(summary_id)
    if row["exported_at"] is None:
        await control_db.execute(
            "UPDATE admin_handoff_summaries SET exported_at = ? WHERE id = ?",
            (utc_now(), summary_id),
        )
    payload = json.loads(str(row["payload_json"]))
    return {
        "summaryId": summary_id,
        "exportedAt": row["exported_at"] or utc_now(),
        "payload": payload,
        "redactionNote": payload.get("redactionNote"),
    }
