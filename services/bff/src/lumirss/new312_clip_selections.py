"""NEW-312 网页选区剪藏包 —— 保留用户主动提交的选中文字，绝不自动抓整页。

- 输入只有用户主动给出的三样：选中文字（纯文本，逐段 ≤2000 字符、
  一包 ≤20 段）、页面 URL（结构校验同剪藏管线，仅 http/https）、
  页面标题；服务器不发起任何网络抓取；
- 选区是用户提供的文本：按纯文本原样存储（绑定参数写库、JSON 输出
  转义），不做 HTML 渲染面；
- 可选把选区包挂到同页已有剪藏（clipRef 存在性由服务端校验，不存在
  → 404，绝不静默丢链接）；
- per-user：选区包在 per-user 库，A 的剪藏包对 B 不可见。
"""

import uuid as _uuid
from typing import Any

from lumirss.clip_fetch import ClipForbidden, validate_clip_url
from lumirss.storage import Database
from lumirss.util import utc_now

MAX_SELECTIONS_PER_PACKAGE = 20
MAX_SELECTION_CHARS = 2000
MAX_NOTE_CHARS = 500
_MAX_PAGE_TITLE_CHARS = 500
_MAX_URL_LENGTH = 2048
_LIST_LIMIT = 50


class SelectionInvalid(ValueError):
    """选区包负载非法（映射 422）。"""


def _clean_page_url(url: Any) -> str:
    if not isinstance(url, str) or not url.strip():
        raise SelectionInvalid("页面 URL 不能为空。")
    clean = url.strip()
    if len(clean) > _MAX_URL_LENGTH:
        raise SelectionInvalid("页面 URL 过长。")
    try:
        validate_clip_url(clean)
    except ClipForbidden as exc:
        raise SelectionInvalid("页面 URL 必须是可公开访问的 http(s) 地址。") from exc
    return clean


def _clean_page_title(title: Any) -> str:
    if title is None:
        return ""
    if not isinstance(title, str):
        raise SelectionInvalid("页面标题必须是字符串。")
    return title.strip()[:_MAX_PAGE_TITLE_CHARS]


def _clean_selections(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list) or not raw:
        raise SelectionInvalid("至少需要一段选区。")
    if len(raw) > MAX_SELECTIONS_PER_PACKAGE:
        raise SelectionInvalid(
            f"一个剪藏包最多 {MAX_SELECTIONS_PER_PACKAGE} 段选区。"
        )
    cleaned: list[dict[str, str]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise SelectionInvalid(f"第 {index + 1} 段选区格式非法。")
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise SelectionInvalid(f"第 {index + 1} 段选区文字不能为空。")
        if len(text) > MAX_SELECTION_CHARS:
            raise SelectionInvalid(
                f"第 {index + 1} 段选区超过 {MAX_SELECTION_CHARS} 字符上限。"
            )
        note = item.get("note") or ""
        if not isinstance(note, str):
            raise SelectionInvalid("选区备注必须是字符串。")
        if len(note) > MAX_NOTE_CHARS:
            raise SelectionInvalid(
                f"第 {index + 1} 段备注超过 {MAX_NOTE_CHARS} 字符上限。"
            )
        cleaned.append({"text": text.strip(), "note": note.strip()})
    return cleaned


class ClipSelectionStore:
    """选区剪藏包持久化（per-user）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create_package(
        self,
        *,
        url: str,
        page_title: str,
        selections: Any,
        clip_ref: str | None = None,
    ) -> dict[str, Any]:
        clean_url = _clean_page_url(url)
        clean_title = _clean_page_title(page_title)
        clean_items = _clean_selections(selections)
        await self._db.migrate()
        clip_uuid: str | None = None
        if clip_ref is not None:
            if not isinstance(clip_ref, str) or not clip_ref.startswith("library:"):
                raise SelectionInvalid("clipRef 必须是 library:<uuid> 形式。")
            clip_uuid = clip_ref.split(":", 1)[1]
            row = await self._db.fetch_one(
                "SELECT 1 AS ok FROM library_clips WHERE item_uuid = ?", (clip_uuid,)
            )
            if row is None:
                from lumirss.library_clips import ClipNotFound

                raise ClipNotFound()
        package_id = str(_uuid.uuid4())
        now = utc_now()

        def _tx(conn: Any) -> None:
            for seq, item in enumerate(clean_items):
                conn.execute(
                    "INSERT INTO clip_selections (id, package_id, url, page_title, clip_item_uuid, seq, text, note, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(_uuid.uuid4()), package_id, clean_url, clean_title,
                        clip_uuid, seq, item["text"], item["note"], now,
                    ),
                )

        from lumirss.db_tx import transaction

        await transaction(self._db, _tx)
        return self._package(
            package_id=package_id,
            url=clean_url,
            page_title=clean_title,
            clip_ref=clip_ref,
            created_at=now,
            items=[
                {"seq": seq, "text": item["text"], "note": item["note"]}
                for seq, item in enumerate(clean_items)
            ],
        )

    async def list_packages(
        self, *, url: str | None = None
    ) -> list[dict[str, Any]]:
        await self._db.migrate()
        if url is not None:
            clean_url = _clean_page_url(url)
            rows = await self._db.fetch_all(
                "SELECT id, package_id, url, page_title, clip_item_uuid, seq, text, note, created_at"
                " FROM clip_selections WHERE url = ? ORDER BY created_at DESC, package_id DESC, seq ASC"
                " LIMIT ?",
                (clean_url, _LIST_LIMIT * MAX_SELECTIONS_PER_PACKAGE),
            )
        else:
            rows = await self._db.fetch_all(
                "SELECT id, package_id, url, page_title, clip_item_uuid, seq, text, note, created_at"
                " FROM clip_selections ORDER BY created_at DESC, package_id DESC, seq ASC"
                " LIMIT ?",
                (_LIST_LIMIT * MAX_SELECTIONS_PER_PACKAGE,),
            )
        packages: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for row in rows:
            pid = str(row["package_id"])
            if pid not in packages:
                packages[pid] = self._package(
                    package_id=pid,
                    url=str(row["url"]),
                    page_title=str(row["page_title"]),
                    clip_ref=(
                        f"library:{row['clip_item_uuid']}"
                        if row["clip_item_uuid"] is not None
                        else None
                    ),
                    created_at=str(row["created_at"]),
                    items=[],
                )
                order.append(pid)
            packages[pid]["selections"].append(
                {
                    "seq": int(row["seq"]),
                    "text": str(row["text"]),
                    "note": str(row["note"]),
                }
            )
        return [packages[pid] for pid in order][:_LIST_LIMIT]

    async def get_package(self, package_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, package_id, url, page_title, clip_item_uuid, seq, text, note, created_at"
            " FROM clip_selections WHERE package_id = ?"
            " ORDER BY created_at DESC, package_id DESC, seq ASC",
            (package_id,),
        )
        if not rows:
            return None
        package = self._package(
            package_id=str(rows[0]["package_id"]),
            url=str(rows[0]["url"]),
            page_title=str(rows[0]["page_title"]),
            clip_ref=(
                f"library:{rows[0]['clip_item_uuid']}"
                if rows[0]["clip_item_uuid"] is not None
                else None
            ),
            created_at=str(rows[0]["created_at"]),
            items=[],
        )
        package["selections"] = [
            {"seq": int(row["seq"]), "text": str(row["text"]), "note": str(row["note"])}
            for row in rows
        ]
        return package

    async def delete_package(self, package_id: str) -> bool:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT 1 AS ok FROM clip_selections WHERE package_id = ? LIMIT 1",
            (package_id,),
        )
        if row is None:
            return False
        await self._db.execute(
            "DELETE FROM clip_selections WHERE package_id = ?", (package_id,)
        )
        return True

    @staticmethod
    def _package(
        *,
        package_id: str,
        url: str,
        page_title: str,
        clip_ref: str | None,
        created_at: str,
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "id": package_id,
            "url": url,
            "pageTitle": page_title,
            "clipRef": clip_ref,
            "createdAt": created_at,
            "selections": items,
        }
