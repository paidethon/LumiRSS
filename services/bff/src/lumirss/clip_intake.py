"""N122 剪藏版本锁定 + N123 剪藏清理预览（intake 批次）。

N122：clips 增加 locked 旗标——锁定时任何自动再提取（refresh）只把
重新抓取的结果存为「候选」（candidate_* 列），绝不覆盖当前展示版本
（revised_content_html 优先，否则原始 content_html）；对展示内容的
覆盖式写入（PATCH revision、应用候选）→ 409 clip_locked。解锁（显式
PUT）后 refresh 直接应用：应用 = 走 F089 的修订槽（revised_* 列），
原始 content_html 依旧永不覆盖（F089 不变量保持）。

N123：清理预览（POST /library/clips/preview-cleanup）——复用
clip_revision.split_blocks 的块级切分，对每块做保守的「建议移除 /
建议保留」分类（导航 / 广告话术 / 短链接列表 → 建议移除；标题 /
段落 / 图片 → 保留）。预览零写入：确认后的保存走既有的 PATCH
revision（同一 sanitize_html 净化管线），原始版本在确认前绝不变动。
"""

import re
import sqlite3
from typing import Any

from lumirss.article_sanitize import sanitize_html
from lumirss.clip_fetch import fetch_extract_sanitize
from lumirss.clip_revision import (
    _BLOCK_SPLIT_RE,
    _TAG_RE,
    content_hash_of,
    recombine,
    split_blocks,
)
from lumirss.db_tx import transaction
from lumirss.library_clips import ClipNotFound, ClipStore
from lumirss.search_library import upsert_search_row
from lumirss.storage import Database
from lumirss.util import utc_now


class ClipLocked(Exception):
    """剪藏已锁定：覆盖展示内容的写入被拒绝（409 clip_locked）。"""


class CandidateNotFound(Exception):
    """没有可应用的候选版本（404 clip_candidate_not_found）。"""


_ROW_SQL = (
    "SELECT item_uuid, content_html, content_text, revised_content_html,"
    " revised_note, revised_at, base_content_hash, locked,"
    " candidate_content_html, candidate_content_text, candidate_title,"
    " candidate_fetched_at"
    " FROM library_clips WHERE item_uuid = ?"
)


def _display_html(row: dict[str, Any]) -> str:
    revised = row["revised_content_html"]
    if revised is not None and revised != "":
        return str(revised)
    return str(row["content_html"])


def _text_of(html: str) -> str:
    return " ".join(_TAG_RE.sub(" ", html).split())[:200]


# -- N123：块级清理分类（保守启发式；预览仅供参考，逐块可手动改） --------

_AD_HINTS = (
    "广告", "推广", "赞助", "促销", "优惠券", "扫码", "关注公众号",
    "订阅我们", "点击购买", "限时", "特惠", "sponsored", "advertisement",
    "promo", "subscribe now", "sign up", "discount",
)
_NAV_HINTS = (
    "首页", "目录", "菜单", "导航", "上一篇", "下一篇", "返回顶部",
    "阅读全文", "查看更多", "相关阅读", "热门推荐", "copyright", "版权所有",
    "all rights reserved", "menu", "navigation", "skip to content",
)


def _block_html_segments(content_html: str) -> list[str]:
    """与 split_blocks 同一切分位置取每块原始 HTML（顺序一致）。"""
    parts = _BLOCK_SPLIT_RE.split(content_html or "")
    segments: list[str] = []
    buffer = ""
    for part in parts:
        buffer += part
        if _BLOCK_SPLIT_RE.fullmatch(part or ""):
            html = buffer.strip()
            buffer = ""
            if html:
                segments.append(html)
    if buffer.strip():
        for paragraph in buffer.split("\n\n"):
            clean = paragraph.strip()
            if clean:
                segments.append(clean)
    return segments


def _anchor_stats(html: str) -> tuple[int, int, int]:
    """(锚点数, 锚点文本总长, 块文本总长)。锚点密度判定短链接列表。"""
    import re

    anchors = re.findall(r"<a\b[^>]*>(.*?)</a>", html, re.IGNORECASE | re.DOTALL)
    anchor_len = sum(len(_TAG_RE.sub("", a).strip()) for a in anchors)
    total = len(_text_of(html))
    return len(anchors), anchor_len, total


def classify_cleanup_blocks(content_html: str) -> list[dict[str, Any]]:
    """N123：[{id, text, keep, reason}]。零写入、纯函数。"""
    blocks: list[dict[str, Any]] = []
    for segment in _block_html_segments(content_html):
        text = _text_of(segment)
        lowered = text.lower()
        keep = True
        reason = "paragraph"
        stats = _anchor_stats(segment)
        anchor_count, anchor_len, total_len = stats
        lowered_html = segment.lower()
        if "<img" in lowered_html:
            reason = "image"
            if not text.strip():
                text = "[图片]"
        elif re.match(r"^<h[1-6]\b", lowered_html):
            reason = "heading"
        elif any(hint in lowered for hint in _AD_HINTS):
            keep = False
            reason = "ad"
        elif anchor_count >= 3 and anchor_len / max(total_len, 1) >= 0.6 and len(text) < 400:
            # 短链接列表：几乎全是锚点文本的短块（导航 / 相关链接）。
            keep = False
            reason = "link_list"
        elif any(hint in lowered for hint in _NAV_HINTS) and len(text) < 120 or len(text) < 8 and anchor_count >= 1:
            keep = False
            reason = "nav"
        blocks.append(
            {
                "id": f"b{len(blocks)}",
                "text": text,
                "keep": keep,
                "reason": reason,
            }
        )
    return blocks


# -- N122：锁定 / 刷新候选 ------------------------------------------------


class ClipIntakeStore:
    """locked / candidate 列的读写（与 ClipRevisionStore 同库同表）。"""

    def __init__(self, db: Database, clip_store: ClipStore) -> None:
        self._db = db
        self._clips = clip_store

    async def _row(self, item_uuid: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(_ROW_SQL, (item_uuid,))
        return dict(row) if row is not None else None

    def has_candidate(self, row: dict[str, Any]) -> bool:
        html = row["candidate_content_html"]
        return html is not None and str(html) != ""

    async def set_locked(self, item_uuid: str, locked: bool) -> dict[str, Any]:
        """显式锁定/解锁（唯一改 locked 的路径）。"""
        row = await self._row(item_uuid)
        if row is None or await self._clips.get_clip(item_uuid) is None:
            raise ClipNotFound(item_uuid)
        await self._db.execute(
            "UPDATE library_clips SET locked = ? WHERE item_uuid = ?",
            (1 if locked else 0, item_uuid),
        )
        return {"ref": f"library:{item_uuid}", "locked": locked}

    async def detail(self, item_uuid: str) -> dict[str, Any] | None:
        """F089 详情 + N122 locked/candidate 字段（展示层诚实标注）。"""
        view = await self._clips.get_clip(item_uuid)
        if view is None:
            return None
        row = await self._row(item_uuid)
        assert row is not None
        revised_html = row["revised_content_html"]
        # F089 语义：None = 未修订；空串 = force 显式清空（也是已修订态）。
        is_revised = revised_html is not None
        display = str(revised_html) if is_revised else str(row["content_html"])
        candidate: dict[str, Any] | None = None
        if self.has_candidate(row):
            candidate = {
                "title": str(row["candidate_title"] or ""),
                "fetchedAt": str(row["candidate_fetched_at"] or ""),
                "text": _text_of(str(row["candidate_content_html"] or "")),
            }
        return {
            "ref": view.ref,
            "url": view.url,
            "title": view.title,
            "byline": view.byline,
            "fetchedAt": view.fetched_at,
            "createdAt": view.created_at,
            "locked": bool(row["locked"]),
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
            "candidate": candidate,
        }

    async def blocks(self, item_uuid: str) -> list[dict[str, str]]:
        row = await self._row(item_uuid)
        if row is None:
            raise ClipNotFound(item_uuid)
        return split_blocks(_display_html(row))

    async def refresh(
        self,
        item_uuid: str,
        *,
        resolver=None,
        ensure_public=None,
    ) -> dict[str, Any]:
        """N122：重新抓取并提取。

        - 未锁定 → 直接应用（写入 F089 修订槽；原始永不覆盖）；
        - 已锁定 → 只存候选；当前展示版本原样不动；
        - 内容未变（hash 一致）→ 诚实 unchanged（不写候选）。
        """
        view = await self._clips.get_clip(item_uuid)
        if view is None:
            raise ClipNotFound(item_uuid)
        row = await self._row(item_uuid)
        assert row is not None
        kwargs: dict[str, Any] = {}
        if resolver is not None:
            kwargs["resolver"] = resolver
        if ensure_public is not None:
            kwargs["ensure_public"] = ensure_public
        article = await fetch_extract_sanitize(view.url, **kwargs)
        current_hash = content_hash_of(_display_html(row))
        new_hash = content_hash_of(article.content_html)
        now = utc_now()
        if new_hash == current_hash and str(article.title) == str(view.title):
            return {
                "ref": view.ref,
                "status": "unchanged",
                "locked": bool(row["locked"]),
                "fetchedAt": now,
            }
        if row["locked"]:
            await self._store_candidate(
                item_uuid,
                content_html=article.content_html,
                content_text=article.content_text,
                title=article.title,
                fetched_at=now,
            )
            return {
                "ref": view.ref,
                "status": "candidate",
                "locked": True,
                "fetchedAt": now,
                "title": article.title,
            }
        applied = await self._apply(
            item_uuid,
            row,
            content_html=article.content_html,
            content_text=article.content_text,
            title=article.title,
            byline=article.byline,
            note="刷新更新（自动重新提取）",
        )
        applied["status"] = "applied"
        applied["locked"] = False
        return applied

    async def _store_candidate(
        self,
        item_uuid: str,
        *,
        content_html: str,
        content_text: str,
        title: str,
        fetched_at: str,
    ) -> None:
        await self._db.execute(
            "UPDATE library_clips SET candidate_content_html = ?, candidate_content_text = ?, candidate_title = ?, candidate_fetched_at = ? WHERE item_uuid = ?",
            (content_html, content_text, title, fetched_at, item_uuid),
        )

    async def _apply(
        self,
        item_uuid: str,
        row: dict[str, Any],
        *,
        content_html: str,
        content_text: str,
        title: str,
        byline: str | None,
        note: str,
        keep_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """把新内容写入修订槽（同一 sanitize_html 净化管线）+ 投影更新。

        keep_ids 非空时先按块重组（N123 清理预览确认后的保存路径）。
        """
        if keep_ids is not None:
            merged = recombine(content_html, keep_ids)
            html_clean = sanitize_html(merged)
        else:
            html_clean = sanitize_html(content_html)
        base_hash = content_hash_of(_display_html(row))
        now = utc_now()

        def _tx(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE library_clips SET revised_content_html = ?, revised_note = ?, revised_at = ?, base_content_hash = ?, candidate_content_html = NULL, candidate_content_text = NULL, candidate_title = NULL, candidate_fetched_at = NULL, title = ?, byline = ?, fetched_at = ? WHERE item_uuid = ?",
                (
                    html_clean,
                    note,
                    now,
                    base_hash,
                    title,
                    byline,
                    now,
                    item_uuid,
                ),
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
                    title=title,
                    body=_text_of(html_clean)[:4000],
                    url=index_row["url"],
                    now=now,
                )

        await transaction(self._db, _tx)
        return {
            "ref": f"library:{item_uuid}",
            "revised": True,
            "revisedAt": now,
            "note": note,
        }

    async def apply_candidate(
        self,
        item_uuid: str,
        *,
        keep_ids: list[str] | None = None,
        note: str = "应用候选版本",
    ) -> dict[str, Any]:
        """应用已存候选（锁定时 409 clip_locked；无候选 404）。"""
        row = await self._row(item_uuid)
        if row is None or await self._clips.get_clip(item_uuid) is None:
            raise ClipNotFound(item_uuid)
        if row["locked"]:
            raise ClipLocked("剪藏已锁定：解锁后才能应用候选版本。")
        if not self.has_candidate(row):
            raise CandidateNotFound(item_uuid)
        title = str(row["candidate_title"] or "")
        applied = await self._apply(
            item_uuid,
            row,
            content_html=str(row["candidate_content_html"]),
            content_text=str(row["candidate_content_text"] or ""),
            title=title,
            byline=None,
            note=note,
            keep_ids=keep_ids,
        )
        applied["status"] = "applied"
        return applied

    async def candidate_html(self, item_uuid: str) -> dict[str, Any]:
        """查看候选（零写入；渲染前客户端仍过 DOMPurify）。"""
        row = await self._row(item_uuid)
        if row is None or await self._clips.get_clip(item_uuid) is None:
            raise ClipNotFound(item_uuid)
        if not self.has_candidate(row):
            raise CandidateNotFound(item_uuid)
        return {
            "ref": f"library:{item_uuid}",
            "title": str(row["candidate_title"] or ""),
            "fetchedAt": str(row["candidate_fetched_at"] or ""),
            "contentHtml": str(row["candidate_content_html"]),
            "contentText": str(row["candidate_content_text"] or ""),
        }

    async def discard_candidate(self, item_uuid: str) -> bool:
        row = await self._row(item_uuid)
        if row is None or not self.has_candidate(row):
            return False
        await self._db.execute(
            "UPDATE library_clips SET candidate_content_html = NULL, candidate_content_text = NULL, candidate_title = NULL, candidate_fetched_at = NULL WHERE item_uuid = ?",
            (item_uuid,),
        )
        return True

    async def save_revision_guarded(
        self,
        item_uuid: str,
        *,
        keep_ids: list[str],
        note: str | None,
        force: bool,
        base_content_hash: str | None,
    ) -> dict[str, Any]:
        """F089 修订保存 + N122 锁定守卫（锁定 → 409 clip_locked）。

        净化仍由 ClipRevisionStore.save_revision 完成（同一管线）；
        这里只先查锁，避免锁定时发生任何覆盖式写入。
        """
        row = await self._row(item_uuid)
        if row is None:
            raise ClipNotFound(item_uuid)
        if row["locked"]:
            raise ClipLocked("剪藏已锁定：解锁后才能修订正文。")
        from lumirss.clip_revision import ClipRevisionStore

        store = ClipRevisionStore(self._db, self._clips)
        return await store.save_revision(
            item_uuid,
            keep_ids=keep_ids,
            note=note,
            force=force,
            base_content_hash=base_content_hash,
        )
