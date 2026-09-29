"""NEW-295 邮件隐私内容遮罩 —— 用户把地址、签名或某段文字标记为分享
时隐藏；原文仍私有保存。

诚实口径（硬规则）：

- 遮罩是用户显式选择的【字面文本】（kind 只是标签：address/signature/
  custom），系统绝不声称自动识别地址或签名——value 必须真实出现在
  该邮件正文里，否则 422（不假装遮了不存在的内容）；
- 遮罩只作用于 share-view（以及 NEW-300 脱敏导出）的展示路径；
  email_materials 原文分毫不动——「原文始终私有保存」；
- 占位符按 kind 给出（如「[已隐藏·地址]」），分享视图里能看出那里
  有过内容，而不是无声删除。

per-user：遮罩在 per-user 库，A 的遮罩对 B 不存在、不影响 B 的分享视图。
"""

import uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

KINDS = ("address", "signature", "custom")
KIND_LABELS = {"address": "地址", "signature": "签名", "custom": "选中文字"}
_MAX_VALUE = 2000

HONESTY_NOTE = (
    "遮罩只作用于分享视图与脱敏导出，原文始终私有保存；系统不会自动"
    "识别地址或签名——你标记什么，分享视图就隐藏什么。"
)


class MaskInvalid(ValueError):
    """遮罩负载非法（映射 422）。"""


class MaskTextNotFound(LookupError):
    """标记文本不在该邮件正文里（映射 422 的另一种稳定错误）。"""


def _placeholder(kind: str) -> str:
    return f"[已隐藏·{KIND_LABELS.get(kind, kind)}]"


def apply_masks(body_text: str, masks: list[dict[str, Any]]) -> str:
    """把全部遮罩按字面文本替换为占位符（纯函数；分享/导出共用）。

    占位符本身永不作为遮罩目标（先应用的遮罩先落地，后面的遮罩不会
    把前面生成的「[已隐藏·…]」再遮一层——先到先得）。"""
    masked = str(body_text or "")
    for mask in masks:
        value = str(mask.get("value") or "")
        if not value or value.startswith("[已隐藏·"):
            continue
        if value in masked:
            masked = masked.replace(value, _placeholder(str(mask.get("kind"))))
    return masked


class EmailMaskStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def _material_body(self, material_id: str) -> str | None:
        row = await self._db.fetch_one(
            "SELECT body_text FROM email_materials WHERE id = ?",
            (material_id,),
        )
        return None if row is None else str(row["body_text"])

    async def list_for(self, material_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT id, kind, value, created_at FROM email_masks"
            " WHERE material_id = ? ORDER BY created_at ASC, id ASC",
            (material_id,),
        )
        return [dict(r) for r in rows]

    async def add_mask(
        self, material_id: str, kind: Any, value: Any
    ) -> dict[str, Any]:
        if kind not in KINDS:
            raise MaskInvalid(f"kind 必须是 {'、'.join(KINDS)} 之一。")
        if not isinstance(value, str) or not value.strip():
            raise MaskInvalid("value 必须是非空文本（你要隐藏的字面内容）。")
        value = value.strip()
        if len(value) > _MAX_VALUE:
            raise MaskInvalid(f"value 过长（≤{_MAX_VALUE}）。")
        if value.startswith("[已隐藏·"):
            raise MaskInvalid("占位符本身不能作为遮罩目标（先到先得，不叠层）。")
        await self._db.migrate()
        body = await self._material_body(material_id)
        if body is None:
            raise MaskInvalid("邮件资料条目不存在。")
        if value not in body:
            raise MaskTextNotFound(
                "标记文本没有出现在这封邮件的正文里——遮罩按字面匹配，"
                "请从正文中选取确切文字。"
            )
        mask_id = f"emk-{uuid.uuid4().hex[:20]}"
        await self._db.execute(
            "INSERT INTO email_masks (id, material_id, kind, value, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (mask_id, material_id, kind, value, utc_now()),
        )
        return {"id": mask_id, "materialId": material_id, "kind": kind, "value": value}

    async def delete_mask(self, mask_id: str) -> bool:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id FROM email_masks WHERE id = ?", (mask_id,)
        )
        if row is None:
            return False
        await self._db.execute("DELETE FROM email_masks WHERE id = ?", (mask_id,))
        return True

    async def share_view(self, material_id: str) -> dict[str, Any] | None:
        """分享视图：应用全部遮罩后的正文 + 遮罩清单 + 诚实口径。"""
        await self._db.migrate()
        body = await self._material_body(material_id)
        if body is None:
            return None
        masks = await self.list_for(material_id)
        return {
            "materialId": material_id,
            "maskedBodyText": apply_masks(body, masks),
            "masks": [
                {
                    "id": str(m["id"]),
                    "kind": str(m["kind"]),
                    "kindLabel": KIND_LABELS.get(str(m["kind"]), str(m["kind"])),
                }
                for m in masks
            ],
            "originalPrivate": True,
            "honestyNote": HONESTY_NOTE,
        }
