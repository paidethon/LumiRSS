"""NEW-350 个人数据删除范围预览 —— 注销（或批量删除）前展示本人的
数据类别与共享副本处理规则；确认后提供**实际处理回执**。

三段式（诚实边界贯穿）：
- 预览（GET /me/deletion/preview）：逐类别真实 COUNT + 共享副本的
  处理规则（谁会被撤销、谁触不到）；「FreshRSS 侧数据不在 Lumi 的
  删除范围内」从预览到回执一以贯之 —— Lumi 删不了 FreshRSS 库，
  也不冒充已删；
- 确认（POST /me/deletion/confirm）：密码复核 → 真实执行可执行项
  （撤销简报 feed / 撤销共享链接 / 停用 API 来源 / 撤销外发 webhook /
  清活动记录 / 标记停用 + 吊销会话）→ 逐类写**已发生**的动作与数量
  （deletion_receipts，0273）；
- 回执（GET /me/deletion/receipts）：动作是已发生事实；retained 清单
  与回执同存 —— 到期后的物理删除没有自动作业（运营者手动执行），
  这一点原文出现在回执里。

per-user：全部处理只作用于本人库/本人凭据；A 确认删的是 A。
"""

import json
from typing import Any

from lumirss.storage import Database

RETAINED_NOTES = (
    "FreshRSS 侧的订阅、条目与已读/收藏状态不在 Lumi 的删除范围内"
    "（由运营者在 FreshRSS 侧处理）",
    "到期后的物理删除没有自动作业：宽限期内运营者可恢复；物理删除由运营者手动执行",
    "设备本地的离线缓存与浏览器数据触达不到（服务端无法清除）",
    "已发生的外部共享访问记录保留（事实不因删除而抹去）",
)


class DeletionConfirmInvalid(ValueError):
    """确认负载非法（映射 422）。"""


def clean_confirm_text(raw: Any) -> str:
    if raw != "DELETE":
        raise DeletionConfirmInvalid('confirmText 必须是大写的 "DELETE"。')
    return str(raw)


async def deletion_counts(db: Database) -> dict[str, int]:
    """逐类别真实计数（COUNT 本人的表；尽力而为，缺失表记 0）。"""
    await db.migrate()
    tables = (
        ("entries", "search_entries"),
        ("clips", "library_clips"),
        ("annotations", "annotations"),
        ("notes", "lumi_notes"),
        ("aiTaskLogs", "ai_task_log"),
        ("searchSnapshots", "search_snapshots"),
        ("personalAccessEvents", "personal_access_events"),
    )
    counts: dict[str, int] = {}
    for key, table in tables:
        try:
            row = await db.fetch_one(f"SELECT COUNT(*) AS n FROM {table}")
            counts[key] = int(row["n"]) if row else 0
        except Exception:  # noqa: BLE001 — 缺表按 0（类别仍如实展示）
            counts[key] = 0
    return counts


async def shared_copy_rules(db: Database, secrets: Any) -> list[dict[str, Any]]:
    """共享副本的处理规则（预览与回执共用同一口径）。"""
    from lumirss.new344_share_links import ShareLinkStore

    links = [
        link
        for link in await ShareLinkStore(db).list_links()
        if link["revokedAt"] is None
    ]
    return [
        {
            "copy": "个人简报 RSS 订阅",
            "rule": "撤销 token：外部订阅地址立即 404",
            "action": "revoke",
        },
        {
            "copy": f"共享链接（当前有效 {len(links)} 条）",
            "rule": "逐条撤销：外部访问者 404；已发生的访问记录保留",
            "action": "revoke",
        },
        {
            "copy": "API 来源 bearer",
            "rule": "停用：外部写入被拒绝",
            "action": "disable",
        },
        {
            "copy": "Webhook 外发订阅",
            "rule": "撤销并删除签名材料：立即停发",
            "action": "revoke",
        },
        {
            "copy": "FreshRSS 侧数据",
            "rule": "不在 Lumi 删除范围内（由运营者在 FreshRSS 侧处理）",
            "action": "none",
        },
    ]


async def save_receipt(
    db: Database,
    *,
    requested_at: str,
    scheduled_deletion_at: str | None,
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    await db.migrate()
    await db.execute(
        "INSERT INTO deletion_receipts (requested_at, scheduled_deletion_at,"
        " actions_json, retained_json) VALUES (?, ?, ?, ?)",
        (
            requested_at,
            scheduled_deletion_at,
            json.dumps(actions, ensure_ascii=False),
            json.dumps(list(RETAINED_NOTES), ensure_ascii=False),
        ),
    )
    row = await db.fetch_one(
        "SELECT id FROM deletion_receipts ORDER BY id DESC LIMIT 1"
    )
    return {
        "id": int(row["id"]),
        "requestedAt": requested_at,
        "scheduledDeletionAt": scheduled_deletion_at,
        "actions": actions,
        "retained": list(RETAINED_NOTES),
    }


async def list_receipts(db: Database, limit: int = 10) -> list[dict[str, Any]]:
    await db.migrate()
    rows = await db.fetch_all(
        "SELECT id, requested_at, scheduled_deletion_at, actions_json,"
        " retained_json FROM deletion_receipts ORDER BY id DESC LIMIT ?",
        (max(1, min(int(limit), 50)),),
    )
    return [
        {
            "id": int(row["id"]),
            "requestedAt": str(row["requested_at"]),
            "scheduledDeletionAt": row["scheduled_deletion_at"],
            "actions": json.loads(str(row["actions_json"])),
            "retained": json.loads(str(row["retained_json"])),
        }
        for row in rows
    ]
