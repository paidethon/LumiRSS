"""NEW-399 帮助文档反馈定位 —— 段落级问题 + 版本/锚点 + 修订回复闭环。

最小诚实版本（硬规则）：

- doc_path 必须相对 ``docs/``（拒绝绝对路径与 ``..``），写入时只读
  校验文件真实存在（不存在 → 400），锚点检测是**结论不是保证**：
  anchorFound=false 只说明在当前文档文本里没找到，仍允许提交；
- version 取提交时的构建版本（LUMIRSS_VERSION）——管理员据此知道
  「哪个版本的文档在说什么」；
- 管理员 resolve 是终态：写修订说明 + 回复，并经 NEW-391 的
  ``record_event`` 给作者落一条真实「帮助已回复」通知（通知只来自
  真实事件——这里就是那个事件）；
- 反馈只给本人看；管理员队列管理员才能看。
"""

import re
from pathlib import Path
from typing import Any

from lumirss.config import LumiSettings
from lumirss.new391_notifications import record_event
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_QUESTION = 1000
_MAX_REPLY = 1000
_MAX_ANCHOR = 200
_MAX_DOC_READ = 512 * 1024
_SAFE_NAME = re.compile(r"^[\w][\w./-]*$")


class FeedbackInvalid(ValueError):
    """反馈载荷非法（400/422）。"""


class FeedbackNotFound(Exception):
    """反馈不存在（404 同形）。"""


def docs_root() -> Path | None:
    """从包位置向上找仓库 docs/（与 whats_new 同口径；找不到 → None）。"""
    here = Path(__file__).resolve().parent
    for parent in [here, *here.parents][:6]:
        candidate = parent / "docs"
        if candidate.is_dir():
            return candidate
    return None


def _resolve_doc(doc_path: str) -> Path:
    if not doc_path or doc_path.startswith(("/", "\\")) or ".." in doc_path:
        raise FeedbackInvalid("docPath 必须是相对 docs/ 的路径。")
    if not _SAFE_NAME.match(doc_path):
        raise FeedbackInvalid("docPath 含不允许的字符。")
    root = docs_root()
    if root is None:
        raise FeedbackInvalid("文档目录不可用，暂时无法提交反馈。")
    resolved = (root / doc_path).resolve()
    if not resolved.is_file() or not resolved.is_relative_to(root.resolve()):
        raise FeedbackInvalid("该文档不存在。")
    return resolved


def _anchor_found(path: Path, anchor: str) -> bool | None:
    """锚点检测：标题行 / 显式 id / wiki 锚。找不到 = False（诚实）。"""
    if not anchor:
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:_MAX_DOC_READ]
    except OSError:
        return False
    lowered = anchor.lower()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") and lowered in stripped.lower():
            return True
        if f'id="{anchor}"' in text or f"#{anchor}" in text:
            return True
    return False


async def create_feedback(
    db: Database,
    user_id: str,
    *,
    doc_path: str,
    anchor: str = "",
    question: str,
) -> dict[str, Any]:
    if not isinstance(question, str) or not question.strip():
        raise FeedbackInvalid("问题内容不能为空。")
    clean_question = question.strip()
    if len(clean_question) > _MAX_QUESTION:
        raise FeedbackInvalid(f"问题内容最长 {_MAX_QUESTION} 字符。")
    clean_doc = str(doc_path or "").strip()
    if not clean_doc:
        raise FeedbackInvalid("docPath 不能为空。")
    path = _resolve_doc(clean_doc)
    clean_anchor = str(anchor or "").strip()
    if len(clean_anchor) > _MAX_ANCHOR:
        raise FeedbackInvalid(f"锚点最长 {_MAX_ANCHOR} 字符。")
    anchor_found = _anchor_found(path, clean_anchor)
    version = LumiSettings().LUMIRSS_VERSION
    await db.migrate()
    now = utc_now()
    new_id = await db.execute(
        "INSERT INTO help_doc_feedback (user_id, doc_path, anchor, anchor_found,"
        " version, question, status, created_at) VALUES (?, ?, ?, ?, ?, ?,"
        " 'open', ?)",
        (
            user_id,
            clean_doc,
            clean_anchor,
            None if anchor_found is None else (1 if anchor_found else 0),
            version,
            clean_question,
            now,
        ),
    )
    return {
        "id": str(new_id),
        "docPath": clean_doc,
        "anchor": clean_anchor,
        "anchorFound": anchor_found,
        "version": version,
        "question": clean_question,
        "status": "open",
        "createdAt": now,
    }


def _row_dto(row: Any) -> dict[str, Any]:
    anchor_found = row["anchor_found"]
    return {
        "id": str(row["id"]),
        "userId": str(row["user_id"]),
        "docPath": str(row["doc_path"]),
        "anchor": str(row["anchor"]),
        "anchorFound": None if anchor_found is None else bool(anchor_found),
        "version": str(row["version"]),
        "question": str(row["question"]),
        "status": str(row["status"]),
        "revisionNote": str(row["revision_note"]),
        "reply": str(row["reply"]),
        "createdAt": str(row["created_at"]),
        "resolvedAt": str(row["resolved_at"]) if row["resolved_at"] else None,
    }


async def list_own_feedback(db: Database, user_id: str) -> dict[str, Any]:
    await db.migrate()
    rows = await db.fetch_all(
        "SELECT * FROM help_doc_feedback WHERE user_id = ?"
        " ORDER BY created_at DESC, id DESC",
        (user_id,),
    )
    return {"items": [_row_dto(row) for row in rows]}


async def list_all_feedback(
    db: Database, *, status: str | None = None
) -> dict[str, Any]:
    await db.migrate()
    if status in ("open", "revised"):
        rows = await db.fetch_all(
            "SELECT * FROM help_doc_feedback WHERE status = ?"
            " ORDER BY created_at ASC, id ASC",
            (status,),
        )
    else:
        rows = await db.fetch_all(
            "SELECT * FROM help_doc_feedback ORDER BY created_at ASC, id ASC"
        )
    return {"items": [_row_dto(row) for row in rows]}


async def resolve_feedback(
    db: Database,
    *,
    feedback_id: str,
    revision_note: str,
    reply: str,
) -> dict[str, Any]:
    if not isinstance(revision_note, str) or not revision_note.strip():
        raise FeedbackInvalid("修订说明不能为空。")
    if not isinstance(reply, str) or not reply.strip():
        raise FeedbackInvalid("回复不能为空。")
    clean_revision = revision_note.strip()[:_MAX_QUESTION]
    clean_reply = reply.strip()[:_MAX_REPLY]
    await db.migrate()
    try:
        numeric = int(str(feedback_id))
    except ValueError as exc:
        raise FeedbackNotFound("没有这条反馈。") from exc
    row = await db.fetch_one(
        "SELECT * FROM help_doc_feedback WHERE id = ?", (numeric,)
    )
    if row is None:
        raise FeedbackNotFound("没有这条反馈。")
    if str(row["status"]) == "revised":
        raise FeedbackInvalid("该反馈已处理（终态）。")
    now = utc_now()
    await db.execute(
        "UPDATE help_doc_feedback SET status = 'revised', revision_note = ?,"
        " reply = ?, resolved_at = ? WHERE id = ?",
        (clean_revision, clean_reply, now, numeric),
    )
    # 真实事件 → NEW-391 通知（帮助已回复；通知不是猜出来的）。
    await record_event(
        db,
        user_id=str(row["user_id"]),
        kind="help_answered",
        source=f"help:doc:{row['doc_path']}",
        title="你的文档反馈已处理",
        body=clean_reply,
        ref=f"help-feedback:{numeric}",
        actionable=False,
    )
    fresh = await db.fetch_one(
        "SELECT * FROM help_doc_feedback WHERE id = ?", (numeric,)
    )
    assert fresh is not None
    return _row_dto(fresh)
