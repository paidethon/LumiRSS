"""NEW-296 邮件附件单独入库 —— 从已导入邮件挑选附件转成独立资料条目，
保留与原邮件的关系。

诚实口径（硬规则）：

- 只能转出【导入时真实存了字节】的附件（email_attachment_blobs
  stored=1；NEW-291 封顶 2 MiB——超限附件只有元数据，转出时如实
  422「内容未存」，绝不给空文件假装成功）；
- 转出 = 独立条目（可单独列出/下载），与原邮件的关系用 parent 字段
  保留；原邮件及其附件清单不受影响（复制引用，不是移动）；
- 同一附件可重复转出（新条目各自独立）；删除附件条目不触碰原邮件。

per-user：附件条目与字节都在 per-user 库，A 的附件对 B 不存在。
"""

import uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

HONESTY_NOTE = (
    "只有导入时存了内容（≤2 MiB）的附件可以转出为独立条目；转出是"
    "复制引用而非移动，原邮件不受影响。"
)


class AttachmentPromoteError(ValueError):
    """转出负载非法（映射 422）。"""


class AttachmentNotFound(LookupError):
    """附件条目或原附件不存在（映射 404）。"""


class EmailAttachmentItemStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def promote(self, material_id: str, ord_: int) -> dict[str, Any]:
        await self._db.migrate()
        material = await self._db.fetch_one(
            "SELECT subject FROM email_materials WHERE id = ?", (material_id,)
        )
        if material is None:
            raise AttachmentNotFound("没有这条邮件资料条目。")
        blob = await self._db.fetch_one(
            "SELECT filename, content_type, size, sha256, stored"
            " FROM email_attachment_blobs WHERE material_id = ? AND ord = ?",
            (material_id, ord_),
        )
        if blob is None:
            raise AttachmentNotFound("这封邮件没有这个序号的附件。")
        if not int(blob["stored"] or 0):
            raise AttachmentPromoteError(
                "该附件导入时未存内容（超出大小上限，只有元数据），"
                "无法转出为独立条目。"
            )
        item_id = f"eai-{uuid.uuid4().hex[:20]}"
        await self._db.execute(
            "INSERT INTO email_attachment_items (id, material_id, ord,"
            " filename, content_type, size, sha256, parent_subject, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item_id,
                material_id,
                ord_,
                str(blob["filename"]),
                str(blob["content_type"]),
                int(blob["size"]),
                str(blob["sha256"]),
                str(material["subject"]),
                utc_now(),
            ),
        )
        return await self.get_item(item_id)  # type: ignore[return-value]

    async def get_item(self, item_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT * FROM email_attachment_items WHERE id = ?", (item_id,)
        )
        if row is None:
            return None
        return self._view(row)

    def _view(self, row: Any) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "materialId": str(row["material_id"]),
            "ord": int(row["ord"]),
            "filename": str(row["filename"]),
            "contentType": str(row["content_type"]),
            "size": int(row["size"]),
            "sha256": str(row["sha256"]),
            "parentSubject": str(row["parent_subject"]),
            "createdAt": str(row["created_at"]),
        }

    async def list_items(self) -> dict[str, Any]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT * FROM email_attachment_items ORDER BY created_at DESC, id DESC"
        )
        return {
            "items": [self._view(r) for r in rows],
            "honestyNote": HONESTY_NOTE,
        }

    async def download(self, item_id: str) -> dict[str, Any] | None:
        """条目 + 原始字节（从 0217 blob 表取，保持单一存储源）。"""
        item = await self.get_item(item_id)
        if item is None:
            return None
        blob = await self._db.fetch_one(
            "SELECT stored, data FROM email_attachment_blobs"
            " WHERE material_id = ? AND ord = ?",
            (item["materialId"], item["ord"]),
        )
        if blob is None or not int(blob["stored"] or 0):
            return None
        item["data"] = blob["data"]
        return item

    async def delete_item(self, item_id: str) -> bool:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id FROM email_attachment_items WHERE id = ?", (item_id,)
        )
        if row is None:
            return False
        await self._db.execute(
            "DELETE FROM email_attachment_items WHERE id = ?", (item_id,)
        )
        return True
