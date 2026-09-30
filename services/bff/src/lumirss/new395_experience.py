"""NEW-395 版本功能体验清单 —— 按当前角色显示实际上线功能的体验标记。

边界（硬规则）：

- 清单本体是 docs/release-notes.json（N198 只读加载器随发布更新）——
  本模块绝不自建功能清单，绝不虚构「已上线」：加载不到就是空清单；
- 角色口径与 N198 一致：adminOnly 条目只出现在 owner/admin 的响应里
  （成员端响应里根本没有，不是前端隐藏）；
- 标记只能打在清单里真实存在的 feature_id 上（未知 id 404）——
  用户体验后显式标记「了解 / 暂不使用」，重复标记 = 覆盖。
"""

from typing import Any

from lumirss.config import LumiSettings
from lumirss.storage import Database
from lumirss.util import utc_now
from lumirss.whats_new import load_release_notes

_STATUSES = ("learned", "later")


class ExperienceInvalid(ValueError):
    """标记非法（422）。"""


class FeatureUnknown(LookupError):
    """feature_id 不在当前清单里（404 同形）。"""


def _inventory() -> dict[str, Any] | None:
    return load_release_notes(LumiSettings().LUMIRSS_RELEASE_NOTES)


def _role_is_admin(role: str | None) -> bool:
    return role in ("owner", "admin")


async def experience_list(
    db: Database, user_id: str, *, role: str | None
) -> dict[str, Any]:
    notes = _inventory()
    if notes is None:
        return {"version": None, "features": [],
                "note": "发布清单不可用，无法展示体验清单。"}
    marks = {
        str(row["feature_id"]): row
        for row in await db.fetch_all(
            "SELECT feature_id, status, updated_at FROM feature_experience_marks"
            " WHERE user_id = ?",
            (user_id,),
        )
    }
    is_admin = _role_is_admin(role)
    features: list[dict[str, Any]] = []
    for feature in notes["features"]:
        if not is_admin and feature.get("adminOnly"):
            continue
        feature_id = str(feature["id"])
        mark_row = marks.get(feature_id)
        features.append(
            {
                "id": feature_id,
                "title": str(feature["title"]),
                "entry": str(feature.get("entry", "")),
                "adminOnly": bool(feature.get("adminOnly")),
                "mark": (
                    {
                        "status": str(mark_row["status"]),
                        "updatedAt": str(mark_row["updated_at"]),
                    }
                    if mark_row is not None
                    else None
                ),
            }
        )
    return {"version": notes["version"], "features": features}


async def mark_feature(
    db: Database, user_id: str, *, feature_id: str, status: str, role: str | None
) -> dict[str, Any]:
    if status not in _STATUSES:
        raise ExperienceInvalid("标记必须是 learned 或 later。")
    notes = _inventory()
    if notes is None:
        raise FeatureUnknown("发布清单不可用。")
    # 角色口径与清单读取一致：成员只能标记自己看得到的条目。
    is_admin = _role_is_admin(role)
    known = {
        str(feature["id"])
        for feature in notes["features"]
        if is_admin or not feature.get("adminOnly")
    }
    if feature_id not in known:
        raise FeatureUnknown("该功能不在当前发布清单里。")
    await db.migrate()
    now = utc_now()
    existing = await db.fetch_one(
        "SELECT id FROM feature_experience_marks WHERE user_id = ? AND feature_id = ?",
        (user_id, feature_id),
    )
    if existing is None:
        await db.execute(
            "INSERT INTO feature_experience_marks"
            " (user_id, feature_id, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (user_id, feature_id, status, now, now),
        )
    else:
        await db.execute(
            "UPDATE feature_experience_marks SET status = ?, updated_at = ?"
            " WHERE id = ?",
            (status, now, existing["id"]),
        )
    return {"featureId": feature_id, "status": status, "updatedAt": now}
