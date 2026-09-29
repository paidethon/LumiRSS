"""NEW-235 笔记模板填空 —— 阅读记录字段模板 + 结构化填充（自由文本保留）。

- 模板 = name + 有序字段 [{key,label}]（key: 小写字母/数字/下划线，
  ≤40 字符；label ≤100；1..20 个字段，key 唯一）。
- 填充存 lumi_notes.template_fill_json = {"templateId", "values"}；
  content_md 仍是正文单一真源——填充是附加结构（与 N079 分栏同一
  先例），自由文本区永不被迫改写。
- values：key 必须 ⊆ 模板字段；缺失字段存空串（诚实：空填 != 拒绝）；
  单值 ≤2000 字符。
"""

import json
import re
import uuid as _uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

MAX_FIELDS = 20
MAX_KEY = 40
MAX_LABEL = 100
MAX_VALUE = 2000
MAX_TEMPLATE_NAME = 100

_KEY_RE = re.compile(r"^[a-z0-9_]{1,40}$")


class NoteTemplateInvalid(ValueError):
    """模板/填充负载非法，映射 422。"""


class NoteTemplateNotFound(Exception):
    """模板或笔记不存在，映射 404。"""


def validate_fields(fields: Any) -> list[dict[str, str]]:
    if not isinstance(fields, list) or not (1 <= len(fields) <= MAX_FIELDS):
        raise NoteTemplateInvalid(f"fields 必须是 1..{MAX_FIELDS} 个字段的数组。")
    seen: set[str] = set()
    cleaned: list[dict[str, str]] = []
    for field in fields:
        if not isinstance(field, dict):
            raise NoteTemplateInvalid("fields 的元素必须是对象。")
        key = field.get("key")
        label = field.get("label")
        if not isinstance(key, str) or not _KEY_RE.match(key):
            raise NoteTemplateInvalid(
                "fields.key 必须是小写字母/数字/下划线（≤40 字符）。"
            )
        if key in seen:
            raise NoteTemplateInvalid(f"fields.key 重复：{key}。")
        if not isinstance(label, str) or not label.strip():
            raise NoteTemplateInvalid("fields.label 必填。")
        if len(label) > MAX_LABEL:
            raise NoteTemplateInvalid(f"fields.label 过长（≤{MAX_LABEL} 字符）。")
        seen.add(key)
        cleaned.append({"key": key, "label": label.strip()})
    return cleaned


def parse_fill(raw: Any, fields: list[dict[str, str]] | None = None) -> dict[str, Any] | None:
    """存储值 → 填充视图；损坏数据诚实归 None（不当错误炸列表）。"""
    if not raw:
        return None
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    values = parsed.get("values")
    if not isinstance(values, dict):
        values = {}
    cleaned = {str(k): str(v) for k, v in values.items()}
    if fields is not None:
        cleaned = {
            field["key"]: cleaned.get(field["key"], "")
            for field in fields
        }
    return {"templateId": str(parsed.get("templateId") or ""), "values": cleaned}


class NoteTemplateStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- 模板 CRUD ---------------------------------------------------------

    async def create(self, name: str, fields: Any) -> dict[str, Any]:
        await self._db.migrate()
        clean_name = str(name or "").strip()
        if not clean_name:
            raise NoteTemplateInvalid("模板名称不能为空。")
        if len(clean_name) > MAX_TEMPLATE_NAME:
            raise NoteTemplateInvalid(f"模板名称过长（≤{MAX_TEMPLATE_NAME} 字符）。")
        clean_fields = validate_fields(fields)
        template_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.execute(
            "INSERT INTO note_field_templates (id, name, fields_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (
                template_id,
                clean_name,
                json.dumps(clean_fields, ensure_ascii=False, separators=(",", ":")),
                now,
                now,
            ),
        )
        return {"id": template_id, "name": clean_name, "fields": clean_fields}

    async def list_templates(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, name, fields_json, created_at FROM note_field_templates "
            "ORDER BY created_at ASC, rowid ASC"
        )
        items: list[dict[str, Any]] = []
        for row in rows:
            try:
                fields = json.loads(str(row["fields_json"] or "[]"))
            except json.JSONDecodeError:
                fields = []
            if not isinstance(fields, list):
                fields = []
            items.append(
                {
                    "id": str(row["id"]),
                    "name": str(row["name"]),
                    "fields": fields,
                    "createdAt": str(row["created_at"]),
                }
            )
        return items

    async def get_template(self, template_id: str) -> dict[str, Any]:
        row = await self._db.fetch_one(
            "SELECT id, name, fields_json FROM note_field_templates WHERE id = ?",
            (template_id,),
        )
        if row is None:
            raise NoteTemplateNotFound(template_id)
        try:
            fields = json.loads(str(row["fields_json"] or "[]"))
        except json.JSONDecodeError:
            fields = []
        if not isinstance(fields, list):
            fields = []
        return {"id": str(row["id"]), "name": str(row["name"]), "fields": fields}

    async def delete_template(self, template_id: str) -> bool:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id FROM note_field_templates WHERE id = ?", (template_id,)
        )
        if row is None:
            return False
        # 已按该模板填充的笔记保留其 values（历史结构诚实保留），
        # 只是模板定义不再可复用。
        await self._db.execute(
            "DELETE FROM note_field_templates WHERE id = ?", (template_id,)
        )
        return True

    # -- 笔记上的填充 -------------------------------------------------------

    async def fill_note(
        self, note_id: str, template_id: str, values: Any
    ) -> dict[str, Any]:
        """把结构化填充写到笔记上（content_md 不动）。模板必须存在；
        values 的 key ⊆ 模板字段；缺失字段补空串。"""
        template = await self.get_template(template_id)
        row = await self._db.fetch_one(
            "SELECT uuid, deleted_at FROM lumi_notes WHERE uuid = ?", (note_id,)
        )
        if row is None or row["deleted_at"] is not None:
            raise NoteTemplateNotFound(note_id)
        if not isinstance(values, dict):
            raise NoteTemplateInvalid("values 必须是对象。")
        allowed = {field["key"] for field in template["fields"]}
        unknown = set(map(str, values)) - allowed
        if unknown:
            raise NoteTemplateInvalid(
                f"values 含模板外的字段：{', '.join(sorted(unknown))}。"
            )
        clean: dict[str, str] = {}
        for field in template["fields"]:
            raw = values.get(field["key"])
            if raw is None:
                clean[field["key"]] = ""
                continue
            if not isinstance(raw, str):
                raise NoteTemplateInvalid(
                    f"values.{field['key']} 必须是字符串。"
                )
            if len(raw) > MAX_VALUE:
                raise NoteTemplateInvalid(
                    f"values.{field['key']} 过长（≤{MAX_VALUE} 字符）。"
                )
            clean[field["key"]] = raw
        payload = json.dumps(
            {"templateId": template_id, "values": clean},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        await self._db.execute(
            "UPDATE lumi_notes SET template_fill_json = ? WHERE uuid = ?",
            (payload, note_id),
        )
        return {
            "noteId": note_id,
            "templateId": template_id,
            "templateName": template["name"],
            "fields": template["fields"],
            "values": clean,
            "contentMdUnchanged": True,
        }

    async def get_fill(self, note_id: str) -> dict[str, Any]:
        """笔记的填充（含模板字段定义；模板已删除 → fields=[]，values
        原样保留——诚实不伪造字段）。笔记不存在 → NoteTemplateNotFound。"""
        row = await self._db.fetch_one(
            "SELECT uuid, template_fill_json, deleted_at FROM lumi_notes WHERE uuid = ?",
            (note_id,),
        )
        if row is None or row["deleted_at"] is not None:
            raise NoteTemplateNotFound(note_id)
        raw = row["template_fill_json"]
        try:
            parsed = json.loads(str(raw)) if raw else None
        except json.JSONDecodeError:
            parsed = None
        if not isinstance(parsed, dict):
            return {"noteId": note_id, "templateId": None, "fields": [], "values": {}}
        template_id = str(parsed.get("templateId") or "")
        fields: list[dict[str, str]] = []
        if template_id:
            try:
                fields = (await self.get_template(template_id))["fields"]
            except NoteTemplateNotFound:
                fields = []
        values = parsed.get("values")
        clean = (
            {str(k): str(v) for k, v in values.items()}
            if isinstance(values, dict)
            else {}
        )
        return {
            "noteId": note_id,
            "templateId": template_id or None,
            "fields": fields,
            "values": clean,
        }
