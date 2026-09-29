"""NEW-298 邮件重复识别复核 —— Message-ID 相同但正文不同的样本列入
冲突队列，由用户选择保留版本。

诚实口径（硬规则）：

- 判定只看两个真实信号：Message-ID 全等（归一化后）+ body_text 的
  sha256。完全一致 → 静默跳过（skipped，附原因）；同 ID 不同正文 →
  【绝不静默覆盖也绝不静默双写】，进冲突队列等用户决定；
- 没有 Message-ID 的邮件不参与重复判定（无真实键可依据，如实不算
  重复——两个都入库）；
- 用户三种选择全部显式：保留原版（丢弃来件）/ 保留来件（替换式新增，
  原版仍在，用户可自行删除——本组没有删除原邮件的入口，不假装提供）/
  两个都留。决定后队列项关闭，结论落 result_id。

per-user：冲突队列在 per-user 库，A 的冲突对 B 不存在。
"""

import base64
import json
import uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

CHOICES = ("keep_existing", "keep_incoming", "keep_both")

HONESTY_NOTE = (
    "相同 Message-ID 且正文一致 → 跳过；同 ID 不同正文 → 由你选择保留"
    "版本（保留来件 = 新增一条，原版仍需你自行处理）。没有 Message-ID"
    " 的邮件不参与重复判定。"
)


async def find_duplicate(
    db: Database, parsed: dict[str, Any]
) -> str | dict[str, Any] | None:
    """导入路径的重复判定。

    返回：
    - None          → 不是重复，正常入库；
    - "skip"        → 完全重复（同 ID 同正文），调用方跳过；
    - {existing_id} → 同 ID 不同正文，调用方记录冲突（dict 带 existing_id）。
    """
    message_id = str(parsed.get("message_id") or "")
    if not message_id:
        return None
    await db.migrate()
    row = await db.fetch_one(
        "SELECT id, body_digest FROM email_materials WHERE message_id = ?"
        " ORDER BY created_at ASC LIMIT 1",
        (message_id,),
    )
    if row is None:
        return None
    if str(row["body_digest"]) == str(parsed.get("body_digest")):
        return "skip"
    return {"existing_id": str(row["id"])}


async def record_conflict(
    db: Database, parsed: dict[str, Any], filename: str, existing_id: str
) -> str:
    """把来件整体（解析结果）存入冲突队列，等待用户复核。

    附件字节 base64 进 incoming_json（≤2MiB/个，0217 封顶）——复核后
    保留来件时不丢附件内容。"""
    await db.migrate()
    existing = await db.fetch_one(
        "SELECT body_digest FROM email_materials WHERE id = ?", (existing_id,)
    )
    storable = {k: v for k, v in parsed.items() if k != "_payloads"}
    payloads = parsed.get("_payloads") or []
    storable["_payloads_b64"] = [
        base64.b64encode(p).decode("ascii") if isinstance(p, bytes) and p else None
        for p in payloads
    ]
    conflict_id = f"edc-{uuid.uuid4().hex[:20]}"
    await db.execute(
        "INSERT INTO email_duplicate_conflicts (id, message_id, existing_id,"
        " existing_digest, incoming_digest, incoming_json, filename, status,"
        " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
        (
            conflict_id,
            str(parsed.get("message_id") or ""),
            existing_id,
            str(existing["body_digest"]) if existing else "",
            str(parsed.get("body_digest") or ""),
            json.dumps(storable, ensure_ascii=False),
            filename[:255],
            utc_now(),
        ),
    )
    return conflict_id


class DuplicateResolveError(ValueError):
    """复核选择非法（映射 422）。"""


class DuplicateConflictNotFound(LookupError):
    """冲突不存在或已解决（映射 404）。"""


async def list_conflicts(db: Database) -> dict[str, Any]:
    await db.migrate()
    rows = await db.fetch_all(
        "SELECT id, message_id, existing_id, existing_digest, incoming_digest,"
        " incoming_json, filename, status, result_id, created_at, resolved_at"
        " FROM email_duplicate_conflicts ORDER BY created_at DESC, id DESC"
    )
    items = []
    for row in rows:
        item = {
            "id": str(row["id"]),
            "messageId": str(row["message_id"]),
            "existingId": str(row["existing_id"]),
            "digestsDiffer": str(row["existing_digest"])
            != str(row["incoming_digest"]),
            "filename": str(row["filename"]),
            "status": str(row["status"]),
            "resultId": str(row["result_id"] or ""),
            "createdAt": str(row["created_at"]),
            "resolvedAt": str(row["resolved_at"] or ""),
        }
        if item["status"] == "pending":
            incoming = json.loads(str(row["incoming_json"] or "{}"))
            item["incomingPreview"] = {
                "subject": str(incoming.get("subject") or ""),
                "fromAddr": str(incoming.get("from_addr") or ""),
                "snippet": str(incoming.get("snippet") or ""),
                "attachmentCount": len(incoming.get("attachments") or []),
            }
        items.append(item)
    return {
        "items": items,
        "choices": list(CHOICES),
        "honestyNote": HONESTY_NOTE,
    }


async def resolve_conflict(
    db: Database, conflict_id: str, choice: str
) -> dict[str, Any]:
    """按用户选择关闭冲突；keep_incoming/both 时把来件真正写入资料库。"""
    await db.migrate()
    if choice not in CHOICES:
        raise DuplicateResolveError(
            f"choice 必须是 {'、'.join(CHOICES)} 之一。"
        )
    row = await db.fetch_one(
        "SELECT * FROM email_duplicate_conflicts WHERE id = ?", (conflict_id,)
    )
    if row is None:
        raise DuplicateConflictNotFound("没有这条冲突。")
    if str(row["status"]) != "pending":
        raise DuplicateConflictNotFound("这条冲突已经复核过了。")

    result_id = ""
    incoming = json.loads(str(row["incoming_json"] or "{}"))
    if choice in ("keep_incoming", "keep_both"):
        from lumirss.new291_email_import import insert_material

        b64_payloads = incoming.pop("_payloads_b64", []) or []
        incoming["_payloads"] = [
            base64.b64decode(p) if isinstance(p, str) and p else None
            for p in b64_payloads
        ]
        result_id = await insert_material(db, incoming, import_kind="duplicate-incoming")

    now = utc_now()
    await db.execute(
        "UPDATE email_duplicate_conflicts SET status = ?, result_id = ?,"
        " resolved_at = ? WHERE id = ?",
        (
            "kept_existing" if choice == "keep_existing"
            else "kept_incoming" if choice == "keep_incoming"
            else "kept_both",
            result_id,
            now,
            conflict_id,
        ),
    )
    return {
        "id": conflict_id,
        "choice": choice,
        "status": str(
            "kept_existing" if choice == "keep_existing"
            else "kept_incoming" if choice == "keep_incoming"
            else "kept_both"
        ),
        "resultId": result_id,
        "honestyNote": (
            "保留来件 = 新增独立条目；原版条目仍在，是否删除由你另行决定。"
        ),
    }
