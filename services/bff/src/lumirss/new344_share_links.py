"""NEW-344 共享链接使用范围 —— 发布链接前限定外部访问者能看到什么：
titles（仅标题目录）/ excerpt（选段）/ full（完整授权正文）。

- token 只存 SHA-256（token_hash 同一口径），明文仅在创建响应出现
  一次；撤销/未知 token 同一 404，不泄露存在性；
- scope 创建后不可变（要改范围就重建链接）——响应与文档如实说明；
- 「预览外部访问者实际能看到什么」与公开路由共用同一个纯函数
  ``render_scope`` —— 所见即所发；
- 私人笔记 / 标注 / 摘要缓存永远不在共享载荷里（表结构上就没有
  这些字段；render 结果 meta 固定列出「永不包含」清单）；
- full（完整授权正文）的创建要求设备信任在有效期内（NEW-346）——
  公开完整正文属敏感操作，路由层强制。

per-user：表在 per-user 库，A 的链接 B 不可见、B 也无法撤销。
"""

import secrets
import sqlite3
from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.token_hash import hash_token, verify_token
from lumirss.util import utc_now

SCOPES = ("titles", "excerpt", "full")
SCOPE_LABELS = {
    "titles": "仅标题目录",
    "excerpt": "选段",
    "full": "完整授权正文",
}
DEFAULT_EXCERPT_CHARS = 200
MAX_EXCERPT_CHARS = 1000
MAX_ITEMS = 50
MAX_TITLE_CHARS = 80

NEVER_INCLUDED = ("私人笔记", "标注", "AI 摘要缓存", "已读状态")

HONESTY_NOTE = (
    "预览与公开访问共用同一渲染函数：外部访问者看到的字段与这里完全一致；"
    "正文来自 Lumi 存储副本（发布后正文不随后续更新变化）。"
)


class ShareLinkInvalid(ValueError):
    """共享链接负载非法（映射 422）。"""


class ShareLinkStateConflict(Exception):
    """状态冲突（已撤销/不存在等，映射 404/409）。"""


def clean_scope(raw: Any) -> str:
    if raw not in SCOPES:
        raise ShareLinkInvalid(f"scope 必须是 {'/'.join(SCOPES)} 之一。")
    return str(raw)


def clean_excerpt_chars(raw: Any, scope: str) -> int:
    if scope != "excerpt":
        return 0
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ShareLinkInvalid("excerptChars 必须是整数。")
    if not 20 <= raw <= MAX_EXCERPT_CHARS:
        raise ShareLinkInvalid(
            f"excerptChars 必须在 20..{MAX_EXCERPT_CHARS} 之间。"
        )
    return raw


def clean_title(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ShareLinkInvalid("title 必须是非空字符串。")
    text = raw.strip()
    if len(text) > MAX_TITLE_CHARS:
        raise ShareLinkInvalid(f"title 最长 {MAX_TITLE_CHARS} 字符。")
    return text


def clean_entry_refs(raw: Any) -> list[str]:
    if not isinstance(raw, list) or not raw:
        raise ShareLinkInvalid("entryRefs 必须是非空字符串数组。")
    refs: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item:
            raise ShareLinkInvalid("entryRefs 的元素必须是非空字符串。")
        if item not in refs:
            refs.append(item)
    if len(refs) > MAX_ITEMS:
        raise ShareLinkInvalid(f"一条共享链接最多 {MAX_ITEMS} 篇文章。")
    return refs


def render_scope(
    scope: str, excerpt_chars: int, entries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """范围渲染（纯函数）：公开路由与预览共用 —— 所见即所发。

    - titles：仅标题目录（标题/来源/时间/原文链接）；
    - excerpt：目录 + 前 excerpt_chars 字符选段（truncated 如实标注）；
    - full：目录 + 完整存储正文。
    """
    rendered: list[dict[str, Any]] = []
    for entry in entries:
        row = {
            "title": str(entry.get("title") or ""),
            "feedTitle": str(entry.get("feedTitle") or ""),
            "url": str(entry.get("url") or ""),
            "publishedAt": entry.get("publishedAt"),
        }
        if scope in ("excerpt", "full"):
            body = str(entry.get("contentText") or "")
            if scope == "excerpt":
                cut = body[: max(1, excerpt_chars)]
                row["excerpt"] = cut
                row["excerptTruncated"] = len(cut) < len(body)
            else:
                row["contentText"] = body
        rendered.append(row)
    return rendered


def render_payload(
    link: dict[str, Any], entries: list[dict[str, Any]]
) -> dict[str, Any]:
    """公开访问者拿到的完整载荷（预览端点返回同一结构）。"""
    return {
        "title": link["title"],
        "scope": link["scope"],
        "scopeLabel": SCOPE_LABELS.get(str(link["scope"]), str(link["scope"])),
        "items": render_scope(
            str(link["scope"]), int(link["excerptChars"]), entries
        ),
        "neverIncluded": list(NEVER_INCLUDED),
        "note": HONESTY_NOTE,
    }


class ShareLinkStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        *,
        title: str,
        scope: str,
        entry_refs: list[str],
        excerpt_chars: int,
        max_uses: int | None = None,
    ) -> dict[str, Any]:
        clean_title_ = clean_title(title)
        clean_scope_ = clean_scope(scope)
        refs = clean_entry_refs(entry_refs)
        chars = clean_excerpt_chars(excerpt_chars, clean_scope_)
        raw = secrets.token_hex(16)
        now = utc_now()
        await self._db.migrate()

        def _tx(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "INSERT INTO share_links (token_hash, title, scope,"
                " excerpt_chars, created_at, max_uses)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    hash_token(raw),
                    clean_title_,
                    clean_scope_,
                    chars,
                    now,
                    max_uses,
                ),
            )
            link_id = int(cursor.lastrowid)
            for position, ref in enumerate(refs):
                conn.execute(
                    "INSERT INTO share_link_items (link_id, entry_ref, position)"
                    " VALUES (?, ?, ?)",
                    (link_id, ref, position),
                )
            return link_id

        link_id = await transaction(self._db, _tx)
        return {
            "id": link_id,
            "token": raw,
            "path": f"/shares/{raw}",
            "title": clean_title_,
            "scope": clean_scope_,
            "excerptChars": chars,
            "maxUses": max_uses,
            "createdAt": now,
            "note": "明文 token 仅此一次返回；scope 创建后不可变（改范围请重建链接）。",
        }

    async def get(self, link_id: int) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, title, scope, excerpt_chars, created_at, revoked_at,"
            " max_uses, use_count, exhausted_at FROM share_links WHERE id = ?",
            (link_id,),
        )
        return self._row(row)

    async def list_links(self, limit: int = 100) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, title, scope, excerpt_chars, created_at, revoked_at,"
            " max_uses, use_count, exhausted_at FROM share_links"
            " ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        )
        return [self._row(row) for row in rows if row is not None]

    async def revoke(self, link_id: int) -> bool:
        link = await self.get(link_id)
        if link is None or link["revokedAt"] is not None:
            return False
        await self._db.execute(
            "UPDATE share_links SET revoked_at = ? WHERE id = ?",
            (utc_now(), link_id),
        )
        return True

    async def resolve_by_token(self, presented: str) -> dict[str, Any] | None:
        """公开路由解析：哈希比对；已撤销 → 视为不存在（同一 404）。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, token_hash, title, scope, excerpt_chars, created_at,"
            " revoked_at, max_uses, use_count, exhausted_at"
            " FROM share_links WHERE token_hash = ?",
            (hash_token(presented),),
        )
        if row is None:
            return None
        if not verify_token(presented, str(row["token_hash"])):
            return None
        if row["revoked_at"] is not None:
            return None
        return self._row(row)

    async def link_entries(self, link_id: int) -> list[dict[str, Any]]:
        """按发布顺序取条目的存储投影（缺失条目如实跳过）。"""
        rows = await self._db.fetch_all(
            "SELECT i.entry_ref, e.title, e.feed_title, e.url,"
            " e.published_at, e.content_text"
            " FROM share_link_items i"
            " LEFT JOIN search_entries e ON e.entry_ref = i.entry_ref"
            " WHERE i.link_id = ? ORDER BY i.position ASC",
            (link_id,),
        )
        entries: list[dict[str, Any]] = []
        for row in rows:
            if row["title"] is None and row["feed_title"] is None:
                continue  # 投影缺失：不伪造占位内容
            entries.append(
                {
                    "entryRef": str(row["entry_ref"]),
                    "title": row["title"],
                    "feedTitle": row["feed_title"],
                    "url": row["url"],
                    "publishedAt": row["published_at"],
                    "contentText": row["content_text"] or "",
                }
            )
        return entries

    @staticmethod
    def _row(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "id": int(row["id"]),
            "title": str(row["title"]),
            "scope": str(row["scope"]),
            "excerptChars": int(row["excerpt_chars"]),
            "createdAt": str(row["created_at"]),
            "revokedAt": row["revoked_at"],
            "maxUses": row["max_uses"],
            "useCount": int(row["use_count"]),
            "exhaustedAt": row["exhausted_at"],
        }
