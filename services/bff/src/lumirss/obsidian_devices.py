"""P16 设备档案存储 — 每用户 obsidian_device_profiles + 导出模板行。

设备档案描述「用户自己设备上的 Obsidian vault 名称」，唯一用途是
obsidian:// URI 生成（obsidian_uri.py）。它与服务器端 vault_path
（env 只读挂载模式的容器内路径，扫描/投影用）完全解耦 —— 这里不存
任何本机路径，vault_identifier 只是可选的本地标识（如 Obsidian 内部
vault id），不参与 URI 生成。

存储走 RoutingDatabase（每用户独立 SQLite）：路由即隔离 —— store 的
SQL 不含 user_id 列，落在谁的上下文就是谁的数据（与 annotations 等
per-user store 同一模式）。CRUD 无 admin/owner 门槛：多设备交接是
每个账户自己的阅读工作流。
"""

import uuid as _uuid
from typing import Any

from lumirss.obsidian_handoff import (
    DEFAULT_NAME_POLICY,
    EXPORT_NAME_POLICIES,
)
from lumirss.obsidian_template import DEFAULT_TEMPLATE, TemplateTooLong
from lumirss.obsidian_uri import validate_platform, validate_vault_name
from lumirss.storage import Database
from lumirss.util import utc_now

MAX_LABEL = 100
MAX_VAULT_NAME = 200
MAX_VAULT_IDENTIFIER = 200

_PLATFORMS = ("windows", "ios", "ipados", "other")


class DeviceProfileInvalid(ValueError):
    """设备档案负载未通过校验。"""


class DeviceProfileNotFound(LookupError):
    """设备档案不存在（或不属于当前上下文用户）——路由层映射 404。"""


def _clean_str(value: Any, limit: int, label: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise DeviceProfileInvalid(f"{label} 必须是字符串。")
    cleaned = value.strip()
    if len(cleaned) > limit:
        raise DeviceProfileInvalid(f"{label} 过长（≤{limit} 字符）。")
    return cleaned


def validate_profile_payload(
    *,
    label: Any,
    vault_name: Any,
    vault_identifier: Any = "",
    platform: Any = "other",
) -> dict[str, str]:
    """Normalize + validate one profile payload (create & update)."""
    clean_label = _clean_str(label, MAX_LABEL, "label")
    if not clean_label:
        raise DeviceProfileInvalid("label 不能为空。")
    clean_vault = _clean_str(vault_name, MAX_VAULT_NAME, "vaultName")
    try:
        clean_vault = validate_vault_name(clean_vault)
    except ValueError as exc:
        raise DeviceProfileInvalid(str(exc)) from exc
    if len(clean_vault) > MAX_VAULT_NAME:
        raise DeviceProfileInvalid(f"vaultName 过长（≤{MAX_VAULT_NAME} 字符）。")
    clean_identifier = _clean_str(
        vault_identifier, MAX_VAULT_IDENTIFIER, "vaultIdentifier"
    )
    if platform is None or platform == "":
        platform = "other"
    try:
        validate_platform(str(platform))
    except ValueError as exc:
        raise DeviceProfileInvalid(str(exc)) from exc
    return {
        "label": clean_label,
        "vault_name": clean_vault,
        "vault_identifier": clean_identifier,
        "platform": str(platform),
    }


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "label": str(row["label"]),
        "vault_name": str(row["vault_name"]),
        "vault_identifier": str(row["vault_identifier"]),
        "platform": str(row["platform"]),
        "created_at": str(row["created_at"]),
    }


class ObsidianDeviceStore:
    """CRUD for per-user Obsidian device profiles (URI generation only)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_profiles(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, label, vault_name, vault_identifier, platform, created_at"
            " FROM obsidian_device_profiles ORDER BY created_at ASC, id ASC"
        )
        return [_row_to_dict(row) for row in rows]

    async def get(self, device_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, label, vault_name, vault_identifier, platform, created_at"
            " FROM obsidian_device_profiles WHERE id = ?",
            (device_id,),
        )
        return _row_to_dict(row) if row is not None else None

    async def create(
        self,
        *,
        label: Any,
        vault_name: Any,
        vault_identifier: Any = "",
        platform: Any = "other",
    ) -> dict[str, Any]:
        payload = validate_profile_payload(
            label=label,
            vault_name=vault_name,
            vault_identifier=vault_identifier,
            platform=platform,
        )
        device_id = str(_uuid.uuid4())
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO obsidian_device_profiles (id, label, vault_name, vault_identifier, platform, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                device_id,
                payload["label"],
                payload["vault_name"],
                payload["vault_identifier"],
                payload["platform"],
                utc_now(),
            ),
        )
        profile = await self.get(device_id)
        assert profile is not None  # 刚插入的行必可读回
        return profile

    async def update(
        self,
        device_id: str,
        *,
        label: Any,
        vault_name: Any,
        vault_identifier: Any = "",
        platform: Any = "other",
    ) -> dict[str, Any] | None:
        payload = validate_profile_payload(
            label=label,
            vault_name=vault_name,
            vault_identifier=vault_identifier,
            platform=platform,
        )
        await self._db.migrate()
        changed = await self._db.execute(
            "UPDATE obsidian_device_profiles SET label = ?, vault_name = ?,"
            " vault_identifier = ?, platform = ? WHERE id = ?",
            (
                payload["label"],
                payload["vault_name"],
                payload["vault_identifier"],
                payload["platform"],
                device_id,
            ),
        )
        if not changed:
            return None  # 不存在（或不属于当前上下文用户）→ 路由层 404
        return await self.get(device_id)

    async def delete(self, device_id: str) -> bool:
        await self._db.migrate()
        changed = await self._db.execute(
            "DELETE FROM obsidian_device_profiles WHERE id = ?", (device_id,)
        )
        return bool(changed)


class ObsidianExportSettingsStore:
    """Per-user export template row (single row, id=1) + N135 命名策略."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_template(self) -> str:
        """The EFFECTIVE template: stored value, else the code default."""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT template FROM obsidian_export_settings WHERE id = 1"
        )
        stored = str(row["template"]) if row is not None else ""
        return stored if stored.strip() else DEFAULT_TEMPLATE

    async def get_stored_template(self) -> str:
        """The RAW stored value ('' = following the code default)."""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT template FROM obsidian_export_settings WHERE id = 1"
        )
        return str(row["template"]) if row is not None else ""

    async def set_template(self, template: str) -> str:
        if len(template) > 20000:
            raise TemplateTooLong("模板过长（≤20000 字符）。")
        await self._db.migrate()
        await self._db.execute(
            "UPDATE obsidian_export_settings SET template = ?, updated_at = ? WHERE id = 1",
            (template, utc_now()),
        )
        return await self.get_template()

    # -- N135 导出重名策略 ------------------------------------------------
    # obsidian://new URI 无法探测目标库内是否已有同名笔记（官方 URI 限
    # 制）：策略是用户显式的选择，不是伪装出来的查重能力。

    async def get_name_policy(self) -> str:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT export_name_policy FROM obsidian_export_settings WHERE id = 1"
        )
        stored = str(row["export_name_policy"]) if row is not None else ""
        return stored if stored in EXPORT_NAME_POLICIES else DEFAULT_NAME_POLICY

    async def set_name_policy(self, policy: str) -> str:
        clean = str(policy or "").strip()
        if clean not in EXPORT_NAME_POLICIES:
            raise DeviceProfileInvalid(
                f"exportNamePolicy 必须是 {'/'.join(EXPORT_NAME_POLICIES)} 之一。"
            )
        await self._db.migrate()
        await self._db.execute(
            "UPDATE obsidian_export_settings SET export_name_policy = ?, updated_at = ? WHERE id = 1",
            (clean, utc_now()),
        )
        return clean
