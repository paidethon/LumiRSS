"""NEW-292 邮件会话串联 —— 把用户导入的同一邮件往返按真实字段组织，
字段不足时允许手动关联。

诚实口径（硬规则）：

- 自动串联只信真实头部字段：In-Reply-To / References 里的 Message-ID
  能在已导入条目中找到 → 归入同一会话（link_mode="references"）；
- 字段不足不是错误：找不到父引用 = 单封（link_mode="none"），用户可
  手动关联（link_mode="manual"）——手动是显式用户决定，系统不猜；
- subject_hint 只作展示提示，绝不参与匹配（不按主题相似度瞎串）；
- 会话内排序按导入先后（created_at），不是邮件 Date 头（该头可伪造/
  缺失，如实说明）。

per-user：会话与成员都在 per-user 库，A 的会话对 B 不存在。
"""

import uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

HONESTY_NOTE = (
    "自动串联只依据邮件真实头部字段（In-Reply-To / References 中的"
    " Message-ID）；字段不足时由你手动关联。会话内按导入先后排序。"
)


def _norm_mid(raw: str) -> str:
    return (raw or "").strip().strip("<>").strip()


def reference_ids(headers: dict[str, str]) -> list[str]:
    """从已入库的头部视图取 In-Reply-To / References 的全部引用 ID。"""
    ids: list[str] = []
    for key in ("In-Reply-To", "References"):
        value = headers.get(key, "")
        for token in str(value).split():
            mid = _norm_mid(token)
            if mid and mid not in ids:
                ids.append(mid)
    return ids


async def assign_thread_on_import(
    db: Database, parsed: dict[str, Any]
) -> tuple[str, str]:
    """导入时按真实引用字段归会话；返回 (thread_id, link_mode)。

    正向：我引用的邮件已有会话 → 加入；引用的是未成串的已存在邮件
    → 新建会话并把它一并拉入（真实引用就是成串证据）。反向：已有
    邮件引用了我 → 同理。都找不到 → 单封（"", "none"）。
    """
    refs = reference_ids(parsed.get("headers") or {})
    own_mid = _norm_mid(str(parsed.get("message_id") or ""))
    subject = str(parsed.get("subject") or "")

    if refs:
        marks = ",".join("?" for _ in refs)
        rows = await db.fetch_all(
            "SELECT thread_id FROM email_materials"
            f" WHERE message_id IN ({marks}) AND thread_id != ''"
            " ORDER BY created_at ASC LIMIT 1",
            tuple(refs),
        )
        if rows:
            return str(rows[0]["thread_id"]), "references"
        parents = await db.fetch_all(
            "SELECT id FROM email_materials"
            f" WHERE message_id IN ({marks}) AND thread_id = ''"
            " ORDER BY created_at ASC",
            tuple(refs),
        )
        if parents:
            thread_id = await create_thread(db, subject)
            for parent in parents:
                await db.execute(
                    "UPDATE email_materials SET thread_id = ?,"
                    " link_mode = 'references' WHERE id = ?",
                    (thread_id, str(parent["id"])),
                )
            return thread_id, "references"

    if own_mid:
        like = f"%{own_mid}%"
        rows = await db.fetch_all(
            "SELECT thread_id FROM email_materials"
            " WHERE thread_id != '' AND headers_json LIKE ?"
            " ORDER BY created_at ASC LIMIT 1",
            (like,),
        )
        if rows:
            return str(rows[0]["thread_id"]), "references"
        rows = await db.fetch_all(
            "SELECT id FROM email_materials"
            " WHERE thread_id = '' AND headers_json LIKE ?"
            " ORDER BY created_at ASC LIMIT 1",
            (like,),
        )
        if rows:
            thread_id = await create_thread(db, subject)
            await db.execute(
                "UPDATE email_materials SET thread_id = ?,"
                " link_mode = 'references' WHERE id = ?",
                (thread_id, str(rows[0]["id"])),
            )
            return thread_id, "references"
    return "", "none"


async def create_thread(db: Database, subject_hint: str) -> str:
    thread_id = f"eth-{uuid.uuid4().hex[:20]}"
    await db.execute(
        "INSERT INTO email_threads (id, subject_hint, created_at) VALUES (?, ?, ?)",
        (thread_id, subject_hint[:500], utc_now()),
    )
    return thread_id


class ThreadLinkError(ValueError):
    """手动关联负载非法（映射 422）。"""


class ThreadTargetNotFound(LookupError):
    """关联目标或会话不存在（映射 404）。"""


async def link_manually(
    db: Database, source_id: str, target_id: str
) -> dict[str, Any]:
    """手动关联：把 source 并入 target 的会话（两边都没有则新建）。

    只做显式用户决定的事：不猜测、不自动扩散到其他条目。
    """
    await db.migrate()
    if source_id == target_id:
        raise ThreadLinkError("不能把一封邮件关联到它自己。")
    source = await db.fetch_one(
        "SELECT id, subject, thread_id FROM email_materials WHERE id = ?",
        (source_id,),
    )
    target = await db.fetch_one(
        "SELECT id, subject, thread_id FROM email_materials WHERE id = ?",
        (target_id,),
    )
    if source is None or target is None:
        raise ThreadTargetNotFound("要关联的邮件资料条目不存在。")

    thread_id = str(target["thread_id"] or "")
    if not thread_id:
        thread_id = str(source["thread_id"] or "")
    if not thread_id:
        thread_id = await create_thread(db, str(target["subject"]))

    await db.execute(
        "UPDATE email_materials SET thread_id = ?, link_mode = 'manual'"
        " WHERE id = ?",
        (thread_id, source_id),
    )
    await db.execute(
        "UPDATE email_materials SET thread_id = ?, link_mode = 'manual'"
        " WHERE id = ? AND thread_id = ''",
        (thread_id, target_id),
    )
    return await thread_view(db, thread_id)


async def thread_view(db: Database, thread_id: str) -> dict[str, Any] | None:
    await db.migrate()
    thread = await db.fetch_one(
        "SELECT id, subject_hint, created_at FROM email_threads WHERE id = ?",
        (thread_id,),
    )
    if thread is None:
        return None
    rows = await db.fetch_all(
        "SELECT id, subject, from_addr, date_hdr, snippet, link_mode,"
        " created_at FROM email_materials WHERE thread_id = ?"
        " ORDER BY created_at ASC, id ASC",
        (thread_id,),
    )
    return {
        "threadId": str(thread["id"]),
        "subjectHint": str(thread["subject_hint"]),
        "members": [
            {
                "id": str(row["id"]),
                "subject": str(row["subject"]),
                "fromAddr": str(row["from_addr"]),
                "date": str(row["date_hdr"]),
                "snippet": str(row["snippet"]),
                "linkMode": str(row["link_mode"] or "none"),
            }
            for row in rows
        ],
        "honestyNote": HONESTY_NOTE,
    }
