"""NEW-300 邮件资料脱敏导出 —— 导出前选择是否保留地址和完整邮件头，
生成清楚的字段删除说明。

诚实口径（硬规则）：

- 默认脱敏：includeAddresses=false 且 includeFullHeaders=false —— 不做
  选择 = 拿到的是脱敏版；保留是显式勾选，绝不「默认顺便带上」；
- removedFields 是【实际生效的删除清单】（字段名 + 原因），同一响应
  返回，让拿到导出文件的人也知道删了什么——不是事后说明文；
- 脱敏与 NEW-295 遮罩叠加：正文先按用户的遮罩清单替换为占位符，再
  导出（正文原文只在 includeBody=true 且未遮罩处保留）；
- 导出只读：不修改库内任何数据；每次导出落一条审计（选项 + 删除清单）。

per-user：导出审计在 per-user 库，A 的导出记录对 B 不可见。
"""

import json
import uuid
from typing import Any

from lumirss.new295_email_masks import KIND_LABELS, apply_masks
from lumirss.storage import Database
from lumirss.util import utc_now

HONESTY_NOTE = (
    "默认脱敏（地址与完整邮件头都不导出）；你勾选保留才包含。每次导出"
    "附带实际删除字段的清单，正文按你的隐私遮罩（NEW-295）先行遮蔽。"
    "导出不修改库内原文。"
)

_MINIMAL_HEADERS = ("Message-ID", "Date")


def build_export_payload(
    material: dict[str, Any],
    masks: list[dict[str, Any]],
    *,
    include_addresses: bool,
    include_full_headers: bool,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """按选择组装导出载荷；返回 (payload, removedFields)。纯函数。

    removedFields 与 payload 严格一致：说删了的字段绝不出现在载荷里。"""
    removed: list[dict[str, str]] = []
    headers: dict[str, str] = dict(material.get("headers") or {})

    if include_addresses:
        from_header = str(headers.get("From") or "")
        to_header = str(headers.get("To") or "")
    else:
        from_header = ""
        to_header = ""
        removed.append(
            {
                "field": "from",
                "reason": "未勾选保留地址：发件人姓名与地址已删除。",
            }
        )
        if to_header:
            removed.append(
                {"field": "to", "reason": "未勾选保留地址：收件人已删除。"}
            )
        removed.append(
            {
                "field": "headers.Cc",
                "reason": "未勾选保留地址：抄送列表已删除。",
            }
        )

    if include_full_headers:
        exported_headers = headers
    else:
        exported_headers = {
            k: v for k, v in headers.items() if k in _MINIMAL_HEADERS
        }
        dropped = sorted(set(headers) - set(_MINIMAL_HEADERS))
        if dropped:
            removed.append(
                {
                    "field": "headers",
                    "reason": f"未勾选保留完整邮件头：已删除 {len(dropped)} 个头部字段"
                    f"（{'、'.join(dropped[:12])}{'…' if len(dropped) > 12 else ''}）。",
                }
            )

    body_masked = apply_masks(str(material.get("bodyText") or ""), masks)
    masked_count = len(masks)
    payload = {
        "kind": "lumirss-email-export",
        "subject": str(material.get("subject") or ""),
        "date": str(material.get("date") or ""),
        "from": from_header,
        "to": to_header,
        "headers": exported_headers,
        "bodyText": body_masked,
        "attachments": material.get("attachments") or [],
        "tags": material.get("tags") or [],
        "maskedRegions": [
            {"kind": str(m["kind"]), "kindLabel": KIND_LABELS.get(str(m["kind"]), str(m["kind"]))}
            for m in masks
        ],
        "maskedRegionCount": masked_count,
        "removedFields": removed,
        "honestyNote": HONESTY_NOTE,
    }
    return payload, removed


class EmailExportStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def export_material(
        self,
        material_id: str,
        *,
        include_addresses: bool,
        include_full_headers: bool,
    ) -> dict[str, Any] | None:
        from lumirss.new291_email_import import EmailMaterialStore

        material = await EmailMaterialStore(self._db).get_material(material_id)
        if material is None:
            return None
        mask_rows = await self._db.fetch_all(
            "SELECT kind, value FROM email_masks WHERE material_id = ?"
            " ORDER BY created_at ASC, id ASC",
            (material_id,),
        )
        masks = [dict(r) for r in mask_rows]
        payload, removed = build_export_payload(
            material,
            masks,
            include_addresses=include_addresses,
            include_full_headers=include_full_headers,
        )
        export_id = f"eex-{uuid.uuid4().hex[:20]}"
        options = {
            "includeAddresses": include_addresses,
            "includeFullHeaders": include_full_headers,
        }
        await self._db.execute(
            "INSERT INTO email_export_logs (id, material_id,"
            " include_addresses, include_full_headers, options_json,"
            " removed_json, exported_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                export_id,
                material_id,
                1 if include_addresses else 0,
                1 if include_full_headers else 0,
                json.dumps(options, ensure_ascii=False),
                json.dumps(removed, ensure_ascii=False),
                utc_now(),
            ),
        )
        return {
            "exportId": export_id,
            "options": options,
            **payload,
        }

    async def list_logs(self, material_id: str | None = None) -> dict[str, Any]:
        await self._db.migrate()
        if material_id:
            rows = await self._db.fetch_all(
                "SELECT * FROM email_export_logs WHERE material_id = ?"
                " ORDER BY exported_at DESC, id DESC LIMIT 50",
                (material_id,),
            )
        else:
            rows = await self._db.fetch_all(
                "SELECT * FROM email_export_logs"
                " ORDER BY exported_at DESC, id DESC LIMIT 50"
            )
        return {
            "items": [
                {
                    "id": str(r["id"]),
                    "materialId": str(r["material_id"]),
                    "options": json.loads(str(r["options_json"] or "{}")),
                    "removedFields": json.loads(str(r["removed_json"] or "[]")),
                    "exportedAt": str(r["exported_at"]),
                }
                for r in rows
            ],
            "honestyNote": HONESTY_NOTE,
        }
