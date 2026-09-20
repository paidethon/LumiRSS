"""F030 问答模板 —— qa_templates 的 SQL 唯一入口。

- 模板是纯文本（≤500 字），与具体文章无关（空文章也可用）；
- 渲染安全由 React 转义兜底（服务端只存原文，绝不做 HTML 组装）；
- 不升级任何权限：会话内普通 CRUD。
"""

import uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_NAME_CHARS = 60
_MAX_TEXT_CHARS = 500
_COLUMNS = "id, name, text, created_at, updated_at"


class QaTemplateNotFound(Exception):
    """模板不存在（404）。"""


class QaTemplateInvalid(ValueError):
    """模板字段非法（422）。"""


def _clean_name(name: Any) -> str:
    if not isinstance(name, str) or not name.strip():
        raise QaTemplateInvalid("name 不能为空。")
    clean = name.strip()
    if len(clean) > _MAX_NAME_CHARS:
        raise QaTemplateInvalid(f"name 过长（最多 {_MAX_NAME_CHARS} 字）。")
    return clean


def _clean_text(text: Any) -> str:
    if not isinstance(text, str) or not text.strip():
        raise QaTemplateInvalid("text 不能为空。")
    clean = text.strip()
    if len(clean) > _MAX_TEXT_CHARS:
        raise QaTemplateInvalid(f"text 过长（最多 {_MAX_TEXT_CHARS} 字）。")
    return clean


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "name": str(row["name"]),
        "text": str(row["text"]),
        "createdAt": str(row["created_at"]),
        "updatedAt": str(row["updated_at"]),
    }


class QaTemplateStore:
    """模板 CRUD（内联 SQL + 绑定参数；写站点 ≤3）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, name: Any, text: Any) -> dict[str, Any]:
        clean_name = _clean_name(name)
        clean_text = _clean_text(text)
        await self._db.migrate()
        template_id = f"qt-{uuid.uuid4().hex[:16]}"
        now = utc_now()
        await self._db.execute(
            "INSERT INTO qa_templates (id, name, text, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (template_id, clean_name, clean_text, now, now),
        )
        created = await self.get(template_id)
        assert created is not None
        return created

    async def list(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            f"SELECT {_COLUMNS} FROM qa_templates ORDER BY created_at ASC, id ASC LIMIT 200",
            (),
        )
        return [_row_to_dict(row) for row in rows]

    async def get(self, template_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            f"SELECT {_COLUMNS} FROM qa_templates WHERE id = ?", (template_id,)
        )
        return _row_to_dict(row) if row is not None else None

    async def rename(
        self, template_id: str, name: Any, text: Any | None = None
    ) -> dict[str, Any] | None:
        exists = await self.get(template_id)
        if exists is None:
            return None
        updates: list[str] = ["name = ?"]
        params: list[Any] = [_clean_name(name)]
        if text is not None:
            updates.append("text = ?")
            params.append(_clean_text(text))
        params.append(utc_now())
        params.append(template_id)
        await self._db.execute(
            f"UPDATE qa_templates SET {', '.join(updates)}, updated_at = ? WHERE id = ?",
            tuple(params),
        )
        updated = await self.get(template_id)
        assert updated is not None
        return updated

    async def delete(self, template_id: str) -> bool:
        await self._db.migrate()
        exists = await self.get(template_id)
        if exists is None:
            return False
        await self._db.execute(
            "DELETE FROM qa_templates WHERE id = ?", (template_id,)
        )
        return True
