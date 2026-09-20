"""F089 剪藏手工修订 —— 保留块重组；原始 content_html 永不覆盖。

- 块切分：复用剪藏正文 HTML 的块级结构（p/h1–h6/li/blockquote/pre/
  div/figcaption 结尾切片）；无块结构（纯文本段落）按空行切段；
- 修订结果先过 ``sanitize_html``（DOMPurify 同源策略：script 绝不
  执行），再写入独立列 revised_content_html；
- 乐观并发：base_content_hash 与「当前展示版本」（修订后优先）的
  hash 不一致 → 409 base_mismatch；
- 全部移除 → 422 must_keep_one；force=True 显式清空（记录说明）；
- 搜索投影更新为修订后文本；原版不入索引；
- 删除修订 = 恢复原始（四列全部清空）。

本文件直接写站点 3 处（修订 UPDATE / 清空 UPDATE / 搜索投影 upsert）。
"""

import hashlib
import re
import sqlite3
from typing import Any

from lumirss.article_sanitize import sanitize_html
from lumirss.db_tx import transaction
from lumirss.library_clips import ClipInvalid, ClipNotFound, ClipStore
from lumirss.search_library import upsert_search_row
from lumirss.storage import Database
from lumirss.util import utc_now

_BLOCK_SPLIT_RE = re.compile(
    r"(</(?:p|h[1-6]|li|blockquote|pre|div|figcaption)>)",
    re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")
_MAX_NOTE_CHARS = 2000


class RevisionConflict(Exception):
    """base mismatch（并发修订），映射 409。"""


class MustKeepOne(Exception):
    """全部块被移除且未显式 force，映射 422。"""


def content_hash_of(html: str) -> str:
    return hashlib.sha256(html.encode("utf-8")).hexdigest()


def split_blocks(content_html: str) -> list[dict[str, str]]:
    """块级切片：[{id, text}]。id 稳定（数组序），text 为纯文本预览。"""
    parts = _BLOCK_SPLIT_RE.split(content_html or "")
    blocks: list[dict[str, str]] = []
    buffer = ""
    for part in parts:
        buffer += part
        if _BLOCK_SPLIT_RE.fullmatch(part or ""):
            html = buffer.strip()
            buffer = ""
            if html:
                blocks.append({"id": f"b{len(blocks)}", "text": _text_of(html)})
    if buffer.strip():
        # 无块结构：按空行段落切。
        for paragraph in re.split(r"\n\s*\n", buffer):
            clean = paragraph.strip()
            if clean:
                blocks.append(
                    {"id": f"b{len(blocks)}", "text": _text_of(clean)}
                )
    return blocks


def _text_of(html: str) -> str:
    return " ".join(_TAG_RE.sub(" ", html).split())[:200]


def recombine(content_html: str, keep_ids: list[str]) -> str:
    """按块 id 保留重组（保持原顺序；id 基于当前展示版本的切分）。"""
    blocks = split_blocks(content_html)
    keep = set(keep_ids)
    return "".join(
        _raw_segment(content_html, blocks, block["id"])
        for block in blocks
        if block["id"] in keep
    )


def _raw_segment(content_html: str, blocks: list[dict[str, str]], block_id: str) -> str:
    """取块 id 对应的原始 HTML 片段（按切分位置重扫，零第三方依赖）。"""
    index = int(block_id[1:])
    parts = _BLOCK_SPLIT_RE.split(content_html or "")
    buffer = ""
    current = 0
    for part in parts:
        buffer += part
        if _BLOCK_SPLIT_RE.fullmatch(part or ""):
            if current == index:
                return buffer.strip()
            current += 1
            buffer = ""
    if buffer.strip() and current == index:
        return buffer.strip()
    return ""


class ClipRevisionStore:
    def __init__(self, db: Database, clip_store: ClipStore) -> None:
        self._db = db
        self._clips = clip_store

    async def _row(self, item_uuid: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT item_uuid, content_html, content_text, revised_content_html, revised_note, revised_at, base_content_hash FROM library_clips WHERE item_uuid = ?",
            (item_uuid,),
        )
        return dict(row) if row is not None else None

    def display_html(self, row: dict[str, Any]) -> str:
        revised = row["revised_content_html"]
        return (
            str(revised)
            if revised is not None and revised != ""
            else str(row["content_html"])
        )

    async def detail(self, item_uuid: str) -> dict[str, Any] | None:
        view = await self._clips.get_clip(item_uuid)
        if view is None:
            return None
        row = await self._row(item_uuid)
        assert row is not None
        revised_html = row["revised_content_html"]
        is_revised = revised_html is not None
        display = str(revised_html) if is_revised else str(row["content_html"])
        return {
            "ref": view.ref,
            "url": view.url,
            "title": view.title,
            "byline": view.byline,
            "fetchedAt": view.fetched_at,
            "createdAt": view.created_at,
            "content": {"html": display, "text": _text_of(display)},
            "original": {
                "html": str(row["content_html"]),
                "text": str(row["content_text"]),
            },
            "revised": (
                {
                    "revisedAt": str(row["revised_at"] or ""),
                    "note": row["revised_note"],
                    "baseContentHash": row["base_content_hash"],
                }
                if is_revised
                else None
            ),
        }

    async def blocks(self, item_uuid: str) -> list[dict[str, str]]:
        row = await self._row(item_uuid)
        if row is None:
            raise ClipNotFound(item_uuid)
        return split_blocks(self.display_html(row))

    async def save_revision(
        self,
        item_uuid: str,
        *,
        keep_ids: list[str],
        note: str | None,
        force: bool,
        base_content_hash: str | None,
    ) -> dict[str, Any]:
        row = await self._row(item_uuid)
        if row is None or await self._clips.get_clip(item_uuid) is None:
            raise ClipNotFound(item_uuid)
        current_hash = content_hash_of(self.display_html(row))
        if (
            base_content_hash is not None
            and base_content_hash != current_hash
        ):
            raise RevisionConflict("内容已被其他修订更新，请刷新后重试。")
        if note is not None and len(note) > _MAX_NOTE_CHARS:
            raise ClipInvalid("修订说明超长（≤2000 字符）。")
        if not keep_ids and not force:
            raise MustKeepOne("至少保留一个块；如需清空请显式 force。")
        if keep_ids:
            merged = recombine(self.display_html(row), keep_ids)
            if not merged.strip():
                raise MustKeepOne("保留块未命中任何内容。")
            clean_html = sanitize_html(merged)
        else:
            clean_html = ""  # force 显式清空（原始版本仍完整保留）
        now = utc_now()

        def _tx(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE library_clips SET revised_content_html = ?, revised_note = ?, revised_at = ?, base_content_hash = ? WHERE item_uuid = ?",
                (clean_html, note, now, current_hash, item_uuid),
            )
            ref = f"library:{item_uuid}"
            index_row = conn.execute(
                "SELECT kind, title, url FROM search_library WHERE ref = ?",
                (ref,),
            ).fetchone()
            if index_row is not None:
                upsert_search_row(
                    conn,
                    ref=ref,
                    kind=str(index_row["kind"]),
                    title=str(index_row["title"]),
                    body=_text_of(clean_html)[:4000],
                    url=index_row["url"],
                    now=now,
                )

        await transaction(self._db, _tx)
        return {
            "ref": f"library:{item_uuid}",
            "revised": True,
            "revisedAt": now,
            "note": note,
            "blocksKept": len(keep_ids),
            "forcedEmpty": not keep_ids,
        }

    async def discard_revision(self, item_uuid: str) -> bool:
        """恢复原始（删修订）：四列清空 + 搜索投影回到原文。"""
        row = await self._row(item_uuid)
        if row is None or row["revised_content_html"] is None:
            return False
        now = utc_now()

        def _tx(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE library_clips SET revised_content_html = NULL, revised_note = NULL, revised_at = NULL, base_content_hash = NULL WHERE item_uuid = ?",
                (item_uuid,),
            )
            ref = f"library:{item_uuid}"
            index_row = conn.execute(
                "SELECT kind, title, url FROM search_library WHERE ref = ?",
                (ref,),
            ).fetchone()
            if index_row is not None:
                upsert_search_row(
                    conn,
                    ref=ref,
                    kind=str(index_row["kind"]),
                    title=str(index_row["title"]),
                    body=str(row["content_text"])[:4000],
                    url=index_row["url"],
                    now=now,
                )

        await transaction(self._db, _tx)
        return True
