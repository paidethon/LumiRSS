"""NEW-241 文章更新差异阅读 —— 显式保存的正文版本 + 段落级差异。

语义边界（模块存在的理由）：

- 版本是用户显式保存的（POST 带 label + 正文文本）；系统绝不自动造
  版本、不 shadow-copy FreshRSS 状态。每篇文章至多保留最近 50 版
  （更早的按 created_at 淘汰——有界存储）；
- 差异：段落级。SequenceMatcher 在两版的段落序列上对齐；replace 块
  内两侧段落相似度 >= 0.5 才算「修改」，否则诚实拆成删+增（不硬凑
  「修改」）。只读、零写入；计数是真实段落数；
- 阅读：GET 单版本返回全文——「用户选择阅读哪个版本」就是读这个；
- entry_ref 只作键，不校验 FreshRSS 存在性（离线资料也允许存版本）。

边界：per-user 库（RoutingDatabase）——版本天然按账户隔离。
"""

import difflib
import re
import sqlite3
import uuid as _uuid
from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_VERSIONS = 50  # 每篇文章版本上限（更早的按 created_at 淘汰）
_MAX_CONTENT_CHARS = 200_000
_MODIFIED_RATIO = 0.5

_PARA_SPLIT = re.compile(r"\n{2,}")


class ArticleVersionInvalid(ValueError):
    """版本操作负载非法（映射 422）。"""


class ArticleVersionNotFound(Exception):
    """文章版本不存在（映射 404）。"""


def split_paragraphs(text: str) -> list[str]:
    """按空行切段；段内换行保留，空段丢弃（诚实切段）。"""
    return [p.strip("\n") for p in _PARA_SPLIT.split(text) if p.strip("\n").strip()]


def diff_paragraphs(from_text: str, to_text: str) -> dict[str, Any]:
    """两段正文之间的段落级差异（纯函数，零 IO）。

    输出块：unchanged / added / removed / modified；modified 只在
    双方段落相似度足够时成立，否则拆成删+增。计数为真实段落数。"""
    old_paras = split_paragraphs(from_text)
    new_paras = split_paragraphs(to_text)
    blocks: list[dict[str, Any]] = []
    added = removed = modified = unchanged = 0

    def _emit(kind: str, old_i: int | None, new_i: int | None) -> None:
        nonlocal added, removed, modified, unchanged
        if kind == "unchanged":
            unchanged += 1
            blocks.append(
                {
                    "type": "unchanged",
                    "oldIndex": old_i,
                    "newIndex": new_i,
                    "text": old_paras[old_i],
                }
            )
        elif kind == "added":
            added += 1
            blocks.append({"type": "added", "oldIndex": None, "newIndex": new_i, "text": new_paras[new_i]})
        elif kind == "removed":
            removed += 1
            blocks.append({"type": "removed", "oldIndex": old_i, "newIndex": None, "text": old_paras[old_i]})
        else:  # modified
            modified += 1
            blocks.append(
                {
                    "type": "modified",
                    "oldIndex": old_i,
                    "newIndex": new_i,
                    "oldText": old_paras[old_i],
                    "newText": new_paras[new_i],
                }
            )

    matcher = difflib.SequenceMatcher(a=old_paras, b=new_paras, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                _emit("unchanged", i1 + offset, j1 + offset)
        elif tag == "delete":
            for i in range(i1, i2):
                _emit("removed", i, None)
        elif tag == "insert":
            for j in range(j1, j2):
                _emit("added", None, j)
        else:  # replace：两侧成对判「修改」，相似度不足则诚实拆开
            pairs = min(i2 - i1, j2 - j1)
            for offset in range(pairs):
                old_i = i1 + offset
                new_i = j1 + offset
                ratio = difflib.SequenceMatcher(
                    a=old_paras[old_i], b=new_paras[new_i], autojunk=False
                ).ratio()
                if ratio >= _MODIFIED_RATIO:
                    _emit("modified", old_i, new_i)
                else:
                    _emit("removed", old_i, None)
                    _emit("added", None, new_i)
            for i in range(i1 + pairs, i2):
                _emit("removed", i, None)
            for j in range(j1 + pairs, j2):
                _emit("added", None, j)

    return {
        "blocks": blocks,
        "added": added,
        "removed": removed,
        "modified": modified,
        "unchanged": unchanged,
        "identical": from_text == to_text,
    }


class ArticleVersionStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- 校验 ------------------------------------------------------------

    @staticmethod
    def _validate_label(label: Any) -> str:
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= 200:
            raise ArticleVersionInvalid("版本标签必须是 1-200 个字符。")
        return label.strip()

    @staticmethod
    def _validate_content(content_text: Any) -> str:
        if not isinstance(content_text, str) or not content_text.strip():
            raise ArticleVersionInvalid("正文文本不能为空。")
        if len(content_text) > _MAX_CONTENT_CHARS:
            raise ArticleVersionInvalid("正文文本超出保存上限（200000 字符）。")
        return content_text

    # -- 版本 ------------------------------------------------------------

    async def save_version(self, entry_ref: str, label: str, content_text: str) -> dict[str, Any]:
        """把当前正文显式保存为一个版本（origin='manual'）。"""
        clean_label = self._validate_label(label)
        clean_content = self._validate_content(content_text)
        if not isinstance(entry_ref, str) or not 1 <= len(entry_ref) <= 300:
            raise ArticleVersionInvalid("entry_ref 非法。")
        version_id = str(_uuid.uuid4())
        now = utc_now()

        def _tx(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO article_saved_versions (id, entry_ref, label, content_text, origin, created_at) "
                "VALUES (?, ?, ?, ?, 'manual', ?)",
                (version_id, entry_ref, clean_label, clean_content, now),
            )
            # cap 50：只保留最近 50 版（created_at 降序，rowid 定平局）
            conn.execute(
                "DELETE FROM article_saved_versions WHERE entry_ref = ? AND rowid NOT IN "
                "(SELECT rowid FROM article_saved_versions WHERE entry_ref = ? "
                "ORDER BY created_at DESC, rowid DESC LIMIT ?)",
                (entry_ref, entry_ref, _MAX_VERSIONS),
            )

        await transaction(self._db, _tx)
        return {
            "id": version_id,
            "entryRef": entry_ref,
            "label": clean_label,
            "contentChars": len(clean_content),
            "origin": "manual",
            "createdAt": now,
        }

    async def list_versions(self, entry_ref: str) -> dict[str, Any]:
        """版本列表（新→旧；不含正文，只有元数据 + 长度）。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, label, origin, created_at, LENGTH(content_text) AS chars "
            "FROM article_saved_versions WHERE entry_ref = ? "
            "ORDER BY created_at DESC, rowid DESC",
            (entry_ref,),
        )
        return {
            "entryRef": entry_ref,
            "items": [
                {
                    "id": str(row["id"]),
                    "label": str(row["label"]),
                    "origin": str(row["origin"]),
                    "createdAt": str(row["created_at"]),
                    "contentChars": int(row["chars"] or 0),
                }
                for row in rows
            ],
        }

    async def get_version(self, entry_ref: str, version_id: str) -> dict[str, Any]:
        """取一个版本全文（阅读所选版本）。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, entry_ref, label, content_text, origin, created_at "
            "FROM article_saved_versions WHERE id = ? AND entry_ref = ?",
            (version_id, entry_ref),
        )
        if row is None:
            raise ArticleVersionNotFound(version_id)
        return {
            "id": str(row["id"]),
            "entryRef": str(row["entry_ref"]),
            "label": str(row["label"]),
            "contentText": str(row["content_text"]),
            "origin": str(row["origin"]),
            "createdAt": str(row["created_at"]),
        }

    async def diff(self, entry_ref: str, from_id: str, to_id: str) -> dict[str, Any]:
        """两个已保存版本之间的段落级差异（只读）。"""
        from_version = await self.get_version(entry_ref, from_id)
        to_version = await self.get_version(entry_ref, to_id)
        result = diff_paragraphs(str(from_version["contentText"]), str(to_version["contentText"]))
        return {
            "entryRef": entry_ref,
            "fromVersion": from_id,
            "toVersion": to_id,
            **result,
        }
