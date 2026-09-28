"""NEW-204 订阅镜像比对 —— 两个候选 feed 的最近条目覆盖差异 + 抉择台账。

语义边界（模块存在的理由）：

- 比对（compare，只读探测）：用户给两个候选 URL（同一站点的镜像 /
  全文 vs 摘要源等），服务端经既有 safe-fetch 边界（SSRF 防护、有界
  body、逐跳校验——与 feed-preview 同一边界）各取一次，**离线**解析
  （feedparser 从不自己联网），并排展示最近条目（≤20）的覆盖差异：
  共有条目数 / 仅 A / 仅 B（按条目 link 精确匹配，保守不归并——
  镜像源的链接可能有无害差异，宁多报差异不误报相同）；
- 一侧失败不掩盖另一侧：失败侧如实带 error，另一侧照常摘要；两侧
  都可用才给出覆盖比对（否则 comparison=null，诚实于「比不了」）；
- 抉择（choose）：比对是探测，**订阅动作仍走既有
  ``POST /api/v1/subscriptions``**——本模块只落一行「选了哪边」的
  台账（含可选理由），绝不代订、绝不动上游；
- 无调度、无缓存：每次 compare 都是显式用户动作。
"""

import uuid as _uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

MAX_COMPARE_ENTRIES = 20
MAX_NOTE = 200


class MirrorCompareInvalid(ValueError):
    """比对输入非法（同 URL/缺参），路由层映射 422。"""


def summarize_feed_document(raw: bytes) -> dict[str, Any]:
    """离线解析 feed 文档 → 摘要（title + 最近 ≤20 条目）。

    解析失败 raise NotAFeedError 族的任何异常都由调用方归为该侧
    error（不掩盖另一侧）。"""
    import feedparser

    parsed = feedparser.parse(raw)
    feed = getattr(parsed, "feed", None) or {}
    entries = list(getattr(parsed, "entries", None) or [])[:MAX_COMPARE_ENTRIES]
    summarized = [
        {
            "link": str(getattr(entry, "link", "") or ""),
            "title": str(getattr(entry, "title", "") or ""),
            "publishedAt": str(
                getattr(entry, "published", "") or getattr(entry, "updated", "") or ""
            ),
        }
        for entry in entries
    ]
    return {
        "title": str(getattr(feed, "title", "") or feed.get("title", "") or ""),
        "entryCount": len(getattr(parsed, "entries", None) or []),
        "comparedEntries": summarized,
    }


def compare_sides(
    summary_a: dict[str, Any] | None, summary_b: dict[str, Any] | None
) -> dict[str, Any] | None:
    """两侧摘要 → 覆盖差异（link 精确匹配；任一侧缺席 → None）。"""
    if summary_a is None or summary_b is None:
        return None
    links_a = [e["link"] for e in summary_a["comparedEntries"] if e["link"]]
    links_b = [e["link"] for e in summary_b["comparedEntries"] if e["link"]]
    set_a, set_b = set(links_a), set(links_b)
    common = set_a & set_b
    return {
        "commonCount": len(common),
        "onlyACount": len(set_a - set_b),
        "onlyBCount": len(set_b - set_a),
        "matchBy": "exact link",
        "note": (
            "按条目 link 精确匹配（保守不归并）；窗口 = 每侧最近"
            f"{MAX_COMPARE_ENTRIES} 条。"
        ),
    }


def _row_to_choice(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "urlA": str(row["url_a"]),
        "urlB": str(row["url_b"]),
        "pickedSide": str(row["picked_side"]),
        "pickedUrl": str(row["picked_url"]),
        "note": row["note"],
        "createdAt": str(row["created_at"]),
    }


class MirrorChoiceStore:
    """抉择台账（SQL 唯一入口；inline literal at each execute site）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self,
        *,
        url_a: str,
        url_b: str,
        picked_side: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        if picked_side not in ("A", "B"):
            raise MirrorCompareInvalid("picked 必须是 'A' 或 'B'。")
        clean_note = (note or "").strip() or None
        if clean_note and len(clean_note) > MAX_NOTE:
            raise MirrorCompareInvalid(f"note 过长（≤{MAX_NOTE} 字符）。")
        choice_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO new204_mirror_choices"
            " (id, url_a, url_b, picked_side, picked_url, note, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                choice_id,
                url_a,
                url_b,
                picked_side,
                url_a if picked_side == "A" else url_b,
                clean_note,
                now,
            ),
        )
        return {
            "id": choice_id,
            "urlA": url_a,
            "urlB": url_b,
            "pickedSide": picked_side,
            "pickedUrl": url_a if picked_side == "A" else url_b,
            "note": clean_note,
            "createdAt": now,
        }

    async def list_choices(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, url_a, url_b, picked_side, picked_url, note, created_at"
            " FROM new204_mirror_choices ORDER BY created_at DESC, id DESC LIMIT 20",
            (),
        )
        return [_row_to_choice(row) for row in rows]
