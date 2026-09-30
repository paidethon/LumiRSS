"""NEW-396 新功能回退偏好 —— 明确可并存的新旧交互二选一。

边界（硬规则）：

- 面注册表只登记**真实并存**的交互面（每项写明新旧两态各自的行为，
  与真实读取/页面路径对应）；本模块不发明交互面，注册表为空时端点
  如实返回空清单；
- ``mode='new'`` 即回到新交互（无期限）；``mode='classic'`` 必带兼容
  期限（面的注册值，默认 90 天）——到期后读取侧一律按新交互生效并
  如实标注 ``expired``，旧实现没有无限期保留；
- 每用户每面至多一条偏好（UNIQUE），重复设置 = 覆盖。
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

DEFAULT_COMPAT_DAYS = 90

# 面注册表：key → 注册事实。每一项的 new/classic 描述与真实路径对应：
# - search_advanced：搜索页「高级多字段面板」（new361 起）与单框简单
#   搜索长期并存——回退即回到单框交互，不隐藏结果本身。
SURFACES: dict[str, dict[str, Any]] = {
    "search_advanced": {
        "label": "搜索交互",
        "newLabel": "高级搜索面板（多字段/短语/时间刷选）",
        "classicLabel": "单框简单搜索",
        "compatDays": DEFAULT_COMPAT_DAYS,
    },
}


class SurfaceUnknown(LookupError):
    """交互面不在注册表里（404 同形）。"""


class ModeInvalid(ValueError):
    """模式非法（422）。"""


async def list_modes(db: Database, user_id: str) -> dict[str, Any]:
    await db.migrate()
    prefs = {
        str(row["surface"]): row
        for row in await db.fetch_all(
            "SELECT * FROM interaction_mode_prefs WHERE user_id = ?", (user_id,)
        )
    }
    now = datetime.now(UTC)
    surfaces: list[dict[str, Any]] = []
    for key, spec in SURFACES.items():
        pref = prefs.get(key)
        mode = "new"
        expires_at = None
        set_at = None
        expired = False
        if pref is not None:
            mode = str(pref["mode"])
            set_at = str(pref["updated_at"])
            if mode == "classic":
                expires_at = str(pref["expires_at"]) if pref["expires_at"] else None
                if expires_at:
                    try:
                        expired = datetime.fromisoformat(
                            expires_at.replace("Z", "+00:00")
                        ) <= now
                    except ValueError:
                        expired = False
                    if expired:
                        mode = "new"
        compat_days = int(spec["compatDays"])
        surfaces.append(
            {
                "key": key,
                "label": str(spec["label"]),
                "newLabel": str(spec["newLabel"]),
                "classicLabel": str(spec["classicLabel"]),
                "mode": mode,
                "chosenMode": (str(pref["mode"]) if pref is not None else None),
                "effectiveMode": mode,
                "expired": expired,
                "expiresAt": expires_at,
                "compatDays": compat_days,
                "setAt": set_at,
            }
        )
    return {
        "surfaces": surfaces,
        "note": "回退只在明确并存的新旧交互间；旧实现按兼容期限保留，到期自动回到新交互。",
    }


async def set_mode(
    db: Database, user_id: str, *, surface: str, mode: str
) -> dict[str, Any]:
    if surface not in SURFACES:
        raise SurfaceUnknown("交互面不存在。")
    if mode not in ("new", "classic"):
        raise ModeInvalid("模式必须是 new 或 classic。")
    await db.migrate()
    now = utc_now()
    compat_days = int(SURFACES[surface]["compatDays"])
    expires_at = (
        (datetime.now(UTC) + timedelta(days=compat_days)).isoformat(timespec="seconds")
        if mode == "classic"
        else None
    )
    existing = await db.fetch_one(
        "SELECT id FROM interaction_mode_prefs WHERE user_id = ? AND surface = ?",
        (user_id, surface),
    )
    if existing is None:
        await db.execute(
            "INSERT INTO interaction_mode_prefs"
            " (user_id, surface, mode, expires_at, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, surface, mode, expires_at, now, now),
        )
    else:
        await db.execute(
            "UPDATE interaction_mode_prefs SET mode = ?, expires_at = ?,"
            " updated_at = ? WHERE id = ?",
            (mode, expires_at, now, existing["id"]),
        )
    listing = await list_modes(db, user_id)
    entry = next(item for item in listing["surfaces"] if item["key"] == surface)
    return entry
