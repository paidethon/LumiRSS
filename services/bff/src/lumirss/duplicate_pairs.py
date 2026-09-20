"""F071 疑似重复审核 — 扫描与判定（library 书签/剪藏）。

相似判定（两者皆是诚实信号，reason 记录命中原因）：
- title_jaccard：标题 token Jaccard ≥ 0.8（ASCII 词 + CJK 单字为 token）；
- same_content_url：normalize_contentUrl 相同但来源不同（item_type 或
  是否来自 RSS 收录）。

- 扫描从不删除/合并任何条目（负向契约：只产「疑似」对）；
- UNIQUE(a_ref,b_ref)（字典序规范化对）：已存在的对不动 → 重复扫描
  幂等；whitelisted 的对因此永不重现。

写站点 2 处（插对 + 更新状态）。
"""

import re as _re
import uuid as _uuid
from typing import Any

from lumirss.url_normalize import normalize_content_url
from lumirss.util import utc_now

_JACCARD_THRESHOLD = 0.8

_STATUSES = ("pending", "confirmed", "ignored", "whitelisted")

_PAIR_SELECT = """SELECT dp.id, dp.a_ref, dp.b_ref, dp.reason, dp.status,
dp.created_at, ba.title AS a_title, bb.title AS b_title,
ba.url AS a_url, bb.url AS b_url
FROM duplicate_pairs dp
LEFT JOIN library_bookmarks ba ON 'library:' || ba.item_uuid = dp.a_ref
LEFT JOIN library_bookmarks bb ON 'library:' || bb.item_uuid = dp.b_ref"""


def _tokens(title: str) -> set[str]:
    """标题 token：ASCII 字词 + CJK 单字（lowercase）。"""
    return set(_re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", (title or "").lower()))


def title_jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    union = ta | tb
    if not union:
        return 0.0
    return len(ta & tb) / len(union)


async def _scan_items(db: Any) -> list[dict[str, Any]]:
    """书签 + 剪藏统一视图：ref/title/url/source（来源=类型+是否 RSS 收录）。"""
    await db.migrate()
    items: list[dict[str, Any]] = []
    bookmark_rows = await db.fetch_all(
        """SELECT b.item_uuid, b.item_type, b.url, b.rss_item_ref, b.title
        FROM library_bookmarks b
        WHERE NOT EXISTS (
          SELECT 1 FROM library_items i
          WHERE i.uuid = b.item_uuid AND i.deleted_at IS NOT NULL
        ) LIMIT 2000"""
    )
    for row in bookmark_rows:
        items.append(
            {
                "ref": f"library:{row['item_uuid']}",
                "title": str(row["title"] or ""),
                "url": row["url"],
                "source": f"bookmark:{row['item_type']}:{'rss' if row['rss_item_ref'] else 'web'}",
            }
        )
    clip_rows = await db.fetch_all(
        """SELECT c.item_uuid, c.url, c.title
        FROM library_clips c
        WHERE NOT EXISTS (
          SELECT 1 FROM library_items i
          WHERE i.uuid = c.item_uuid AND i.deleted_at IS NOT NULL
        ) LIMIT 2000"""
    )
    for row in clip_rows:
        items.append(
            {
                "ref": f"library:{row['item_uuid']}",
                "title": str(row["title"] or ""),
                "url": row["url"],
                "source": "clip",
            }
        )
    return items


def _compare(a: dict[str, Any], b: dict[str, Any]) -> str | None:
    if a["ref"] == b["ref"]:
        return None
    url_a, url_b = normalize_content_url(a["url"] or ""), normalize_content_url(b["url"] or "")
    same_url = url_a is not None and url_a == url_b
    if same_url and a["source"] != b["source"]:
        return "same_content_url"
    if title_jaccard(a["title"], b["title"]) >= _JACCARD_THRESHOLD:
        return "title_jaccard"
    return None


async def scan(db: Any) -> dict[str, Any]:
    """全量扫描：新对插入 pending；已存在的对（任何状态）不动。"""
    items = await _scan_items(db)
    created = 0
    compared: set[frozenset[str]] = set()
    for i, a in enumerate(items):
        for b in items[i + 1 :]:
            key = frozenset((a["ref"], b["ref"]))
            if key in compared or len(key) < 2:
                continue
            compared.add(key)
            reason = _compare(a, b)
            if reason is None:
                continue
            a_ref, b_ref = sorted((a["ref"], b["ref"]))
            row = await db.fetch_one(
                "SELECT id FROM duplicate_pairs WHERE a_ref = ? AND b_ref = ?",
                (a_ref, b_ref),
            )
            if row is not None:
                continue  # 已存在的对不动（含 whitelisted → 永不重现）
            await db.execute(
                "INSERT INTO duplicate_pairs (id, a_ref, b_ref, reason, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
                (str(_uuid.uuid4()), a_ref, b_ref, reason, utc_now()),
            )
            created += 1
    total = await db.fetch_one("SELECT COUNT(*) AS n FROM duplicate_pairs WHERE status = 'pending'")
    return {
        "scanned": len(items),
        "created": created,
        "pending": int(total["n"]) if total is not None else 0,
    }


def _pair_row(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "aRef": str(row["a_ref"]),
        "bRef": str(row["b_ref"]),
        "reason": str(row["reason"]),
        "status": str(row["status"]),
        "createdAt": str(row["created_at"]),
        "aTitle": row["a_title"],
        "bTitle": row["b_title"],
        "aUrl": row["a_url"],
        "bUrl": row["b_url"],
    }


async def list_pairs(db: Any, status: str | None = None) -> list[dict[str, Any]]:
    await db.migrate()
    if status is not None and status not in _STATUSES:
        return []
    rows = await db.fetch_all(
        _PAIR_SELECT + " WHERE (? IS NULL OR dp.status = ?) ORDER BY dp.created_at DESC LIMIT 500",
        (status, status),
    )
    return [_pair_row(row) for row in rows]


async def get_pair(db: Any, pair_id: str) -> dict[str, Any] | None:
    await db.migrate()
    row = await db.fetch_one(_PAIR_SELECT + " WHERE dp.id = ?", (pair_id,))
    return _pair_row(row) if row is not None else None


async def set_status(db: Any, pair_id: str, status: str) -> dict[str, Any] | None:
    if status not in _STATUSES:
        raise ValueError(f"status must be one of {_STATUSES}.")
    await db.migrate()
    await db.execute(
        "UPDATE duplicate_pairs SET status = ? WHERE id = ?",
        (status, pair_id),
    )
    return await get_pair(db, pair_id)
