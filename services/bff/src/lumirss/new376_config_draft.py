"""NEW-376 实例配置草案审查 —— 非敏感配置变更先成草案再应用。

- 可草案的键是本模块的 allow-list（只有真实存在、真实被消费的实例
  配置才进名单；当前唯一键：``allow_public_registration``——注册
  政策，auth 注册路径实时消费）。敏感凭据、env 型配置一律不进；
- 草案持久化：draft_value + 当前值 + 校验结果 + 生效条件，apply 前
  任何人（包括管理员）都无法让草案「悄悄生效」；
- 应用 = step-up（config_draft_apply，target=操作管理员本人）+
  InstanceSettingsStore.set（与既有注册政策端点同一执行点）+ 审计。
  set 语义状态机 draft → applied | discarded，行永不删除；
- 校验按键类型：bool 键只认 "0"/"1"；值域错误在草案阶段就报，不存
  一份注定失败的草案。
"""

import json
import uuid
from typing import Any

from lumirss.db_tx import transaction
from lumirss.util import utc_now

# key → {type, label, effectiveNotes}
DRAFTABLE_KEYS: dict[str, dict[str, Any]] = {
    "allow_public_registration": {
        "type": "bool",
        "label": "公开注册开关",
        "effectiveNotes": [
            "立即生效：新注册请求按新值判定（auth 注册路径实时读取）。",
            "已激活账户与既有会话不受影响。",
        ],
    },
}


class ConfigDraftInvalid(ValueError):
    """草案载荷非法 / 值不合法（422）。"""


class ConfigDraftNotFound(Exception):
    """草案不存在（404）。"""


class ConfigDraftStateInvalid(Exception):
    """草案已收尾，不能应用/再废弃（409）。"""


def validate_value(key: str, value: Any) -> str:
    spec = DRAFTABLE_KEYS.get(key)
    if spec is None:
        raise ConfigDraftInvalid(f"该键不可草案：{key}。")
    if not isinstance(value, str):
        raise ConfigDraftInvalid("value 必须是字符串。")
    cleaned = value.strip()
    if spec["type"] == "bool" and cleaned not in ("0", "1"):
        raise ConfigDraftInvalid("布尔键只接受 \"0\" 或 \"1\"。")
    return cleaned


async def create_draft(
    control_db: Any, *, key: str, value: Any, by: str
) -> dict[str, Any]:
    cleaned = validate_value(key, value)
    from lumirss.instance_settings import InstanceSettingsStore

    store = InstanceSettingsStore(control_db)
    current = await store.get(key)
    await control_db.migrate()
    draft_id = uuid.uuid4().hex
    validation: dict[str, Any] = {
        "ok": True,
        "type": DRAFTABLE_KEYS[key]["type"],
        "checks": [
            "键在可草案 allow-list 内",
            f"值通过 {DRAFTABLE_KEYS[key]['type']} 校验",
        ],
    }
    await control_db.execute(
        "INSERT INTO admin_config_drafts (id, key, draft_value, current_value, validation, effective_notes, status, created_by, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?)",
        (
            draft_id,
            key,
            cleaned,
            current,
            json.dumps(validation, ensure_ascii=False),
            json.dumps(DRAFTABLE_KEYS[key]["effectiveNotes"], ensure_ascii=False),
            by,
            utc_now(),
        ),
    )
    return {
        "draftId": draft_id,
        "key": key,
        "keyLabel": DRAFTABLE_KEYS[key]["label"],
        "currentValue": current,
        "draftValue": cleaned,
        "validation": validation,
        "effectiveNotes": DRAFTABLE_KEYS[key]["effectiveNotes"],
        "status": "draft",
        "differs": cleaned != current,
    }


def _row_json(row: Any) -> dict[str, Any]:
    return {
        "draftId": str(row["id"]),
        "key": str(row["key"]),
        "keyLabel": DRAFTABLE_KEYS.get(str(row["key"]), {}).get("label", str(row["key"])),
        "currentValue": str(row["current_value"]),
        "draftValue": str(row["draft_value"]),
        "validation": json.loads(str(row["validation"])),
        "effectiveNotes": json.loads(str(row["effective_notes"])),
        "status": str(row["status"]),
        "createdBy": str(row["created_by"]),
        "createdAt": str(row["created_at"]),
        "appliedBy": row["applied_by"],
        "appliedAt": row["applied_at"],
    }


async def get_draft(control_db: Any, draft_id: str) -> dict[str, Any] | None:
    await control_db.migrate()
    row = await control_db.fetch_one(
        "SELECT * FROM admin_config_drafts WHERE id = ?", (draft_id,)
    )
    return _row_json(row) if row is not None else None


async def list_drafts(control_db: Any, limit: int = 20) -> list[dict[str, Any]]:
    await control_db.migrate()
    rows = await control_db.fetch_all(
        "SELECT * FROM admin_config_drafts ORDER BY created_at DESC, id DESC LIMIT ?",
        (max(1, min(limit, 50)),),
    )
    return [_row_json(row) for row in rows]


async def apply_draft(control_db: Any, *, draft_id: str, by: str) -> dict[str, Any]:
    await control_db.migrate()

    def _write(conn: Any) -> dict[str, Any]:
        row = conn.execute(
            "SELECT key, draft_value, status FROM admin_config_drafts WHERE id = ?",
            (draft_id,),
        ).fetchone()
        if row is None:
            raise ConfigDraftNotFound(draft_id)
        if str(row["status"]) != "draft":
            raise ConfigDraftStateInvalid(draft_id)
        conn.execute(
            "UPDATE admin_config_drafts SET status = 'applied', applied_by = ?, applied_at = ?, settled_at = ? WHERE id = ?",
            (by, utc_now(), utc_now(), draft_id),
        )
        return {"draftId": draft_id, "key": str(row["key"]), "value": str(row["draft_value"])}

    result = await transaction(control_db, _write)
    # 与既有注册政策端点同一执行点（InstanceSettingsStore.set）。
    from lumirss.instance_settings import InstanceSettingsStore

    await InstanceSettingsStore(control_db).set(result["key"], result["value"], by)
    return {**result, "status": "applied"}


async def discard_draft(control_db: Any, *, draft_id: str, by: str) -> dict[str, Any]:
    await control_db.migrate()

    def _write(conn: Any) -> dict[str, Any]:
        row = conn.execute(
            "SELECT status FROM admin_config_drafts WHERE id = ?", (draft_id,)
        ).fetchone()
        if row is None:
            raise ConfigDraftNotFound(draft_id)
        if str(row["status"]) != "draft":
            raise ConfigDraftStateInvalid(draft_id)
        conn.execute(
            "UPDATE admin_config_drafts SET status = 'discarded', settled_at = ? WHERE id = ?",
            (utc_now(), draft_id),
        )
        return {"draftId": draft_id, "status": "discarded", "by": by}

    return await transaction(control_db, _write)
