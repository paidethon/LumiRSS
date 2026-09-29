"""NEW-277 模型配置用途约束 —— 每个配置档允许处理的任务类型。

- allowed_purposes：ai_profiles.PURPOSES 的非空子集；只对显式映射到
  用途的「非默认档」生效（default 档不可约束——未映射用途全部回落
  default，约束它等于切断所有兜底）；
- 触发不允许的用途 → AiPurposeNotAllowed（409 ai_purpose_not_allowed，
  附 allowedPurposes），绝不静默换模型——换哪个模型是用户的选择，
  purpose-options 端点给出「已配置且允许」的候选；
- 无约束行 = 未约束（现行为零变化）。

per-user：约束表在 per-user 库；profile 定义本身也是 per-user 的。
"""

import json
from typing import Any

from lumirss.ai_profiles import (
    DEFAULT_PROFILE_ID,
    PURPOSES,
    AiProfileStore,
)
from lumirss.storage import Database
from lumirss.util import utc_now


class ConstraintInvalid(ValueError):
    """约束负载非法（映射 422）。"""


class AiPurposeNotAllowed(Exception):
    """被约束的配置档不允许该用途（映射 409）。"""

    def __init__(
        self, profile_id: str, profile_label: str, purpose: str,
        allowed_purposes: list[str],
    ) -> None:
        super().__init__(
            f"配置档「{profile_label}」被限定为 {allowed_purposes}，"
            f"不允许处理 {purpose}。请改用其他已配置且允许该用途的模型。"
        )
        self.profile_id = profile_id
        self.profile_label = profile_label
        self.purpose = purpose
        self.allowed_purposes = allowed_purposes


def clean_allowed_purposes(raw: Any) -> list[str]:
    if not isinstance(raw, list) or not raw:
        raise ConstraintInvalid("allowedPurposes 必须是非空数组。")
    seen: list[str] = []
    for item in raw:
        if item not in PURPOSES:
            raise ConstraintInvalid(
                f"未知用途「{item}」；可用用途：{'、'.join(PURPOSES)}。"
            )
        if item not in seen:
            seen.append(item)
    return seen


class PurposeConstraintStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def set_constraint(
        self, profiles: AiProfileStore, profile_id: str, raw: Any
    ) -> dict[str, Any]:
        if profile_id == DEFAULT_PROFILE_ID:
            raise ConstraintInvalid(
                "default 档不可约束：未映射用途全部回落 default，"
                "约束它等于切断所有兜底。"
            )
        profile = await profiles.get_profile(profile_id)  # 不存在 → 404 族
        clean = clean_allowed_purposes(raw)
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO ai_purpose_constraints (profile_id, allowed_purposes, "
            "updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(profile_id) DO UPDATE SET allowed_purposes = excluded.allowed_purposes, "
            "updated_at = excluded.updated_at",
            (profile_id, json.dumps(clean), utc_now()),
        )
        return self.view(profile_id, profile["label"], clean)

    async def delete_constraint(self, profile_id: str) -> bool:
        if profile_id == DEFAULT_PROFILE_ID:
            raise ConstraintInvalid("default 档没有约束可删。")
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT profile_id FROM ai_purpose_constraints WHERE profile_id = ?",
            (profile_id,),
        )
        if row is None:
            return False
        await self._db.execute(
            "DELETE FROM ai_purpose_constraints WHERE profile_id = ?",
            (profile_id,),
        )
        return True

    async def get_constraint(self, profile_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT allowed_purposes FROM ai_purpose_constraints WHERE profile_id = ?",
            (profile_id,),
        )
        if row is None:
            return None
        try:
            allowed = json.loads(str(row["allowed_purposes"]))
        except json.JSONDecodeError:
            return None
        if not isinstance(allowed, list) or not allowed:
            return None
        return {
            "profileId": profile_id,
            "allowedPurposes": [str(item) for item in allowed if item in PURPOSES],
        }

    def view(
        self, profile_id: str, profile_label: str, allowed: list[str]
    ) -> dict[str, Any]:
        return {
            "profileId": profile_id,
            "profileLabel": profile_label,
            "allowedPurposes": allowed,
            "purposes": list(PURPOSES),
        }

    async def purpose_options(
        self, profiles: AiProfileStore, purpose: str
    ) -> dict[str, Any]:
        """触发某用途时的可选模型：已配置（启用+有 key）且约束允许。"""
        if purpose not in PURPOSES:
            raise ConstraintInvalid(
                f"未知用途「{purpose}」；可用用途：{'、'.join(PURPOSES)}。"
            )
        mapping = await profiles.load_purposes()
        mapped = mapping.get(purpose, DEFAULT_PROFILE_ID)
        options: list[dict[str, Any]] = []
        for profile in await profiles.list_profiles():
            constraint = await self.get_constraint(str(profile["id"]))
            allowed = (
                constraint["allowedPurposes"] if constraint else list(PURPOSES)
            )
            eligible = bool(
                profile["enabled"]
                and profile["keyConfigured"]
                and purpose in allowed
            )
            options.append(
                {
                    "profileId": str(profile["id"]),
                    "label": str(profile["label"]),
                    "model": str(profile["model"]),
                    "enabled": bool(profile["enabled"]),
                    "keyConfigured": bool(profile["keyConfigured"]),
                    "constrained": constraint is not None,
                    "allowedPurposes": allowed,
                    "eligible": eligible,
                    "isCurrentMapping": str(profile["id"]) == mapped,
                }
            )
        blocked = mapped != DEFAULT_PROFILE_ID and any(
            option["isCurrentMapping"] and not option["eligible"]
            for option in options
        )
        return {
            "purpose": purpose,
            "purposes": list(PURPOSES),
            "mappedProfileId": mapped,
            "blocked": blocked,
            "options": options,
            "honestyNote": (
                "约束只对显式映射到用途的配置档生效；default 兜底不可约束。"
                "被阻断时请把该用途映射到其他已配置且允许的模型。"
            ),
        }


async def assert_purpose_allowed(
    db: Database, profiles: AiProfileStore, purpose: str
) -> None:
    """用途触发点守卫：映射档被约束且不允许 → AiPurposeNotAllowed。"""
    if purpose not in PURPOSES:
        return
    mapping = await profiles.load_purposes()
    mapped = mapping.get(purpose, DEFAULT_PROFILE_ID)
    if mapped == DEFAULT_PROFILE_ID:
        return
    store = PurposeConstraintStore(db)
    constraint = await store.get_constraint(mapped)
    if constraint is None or purpose in constraint["allowedPurposes"]:
        return
    profile = await profiles.get_profile(mapped)
    raise AiPurposeNotAllowed(
        mapped,
        str(profile["label"]),
        purpose,
        constraint["allowedPurposes"],
    )
