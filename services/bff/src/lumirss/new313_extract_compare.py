"""NEW-313 剪藏正文候选对照 —— 同一次抓取的两种提取结果，用户选择。

诚实口径：

- 两种候选来自同一次有界抓取（fetch 继承 clip_fetch 的 SSRF 预检 +
  pinned dial + 5MB/30s 上限）的同一份原始 HTML：
  * ``article``：article_extract 的正文评分提取（现状管线同款）；
  * ``fulltext``：保守的保真兜底（丢 script/style/导航容器后序列化
    body），页式排版站常常比评分法更完整；
- 两份候选存储前都过 sanitize_html（与创建剪藏同一净化边界）；
- 「原站允许的前提下」= 抓取即既有剪藏管线的匿名有界抓取；不可达
  （超时/DNS/HTTP 错误）→ 诚实失败（502 clip_fetch_failed），绝不拿
  旧正文假装是新候选；
- 选择只是「切换展示版本」：写入 F089 修订槽（revised_content_html +
  revised_at），原始 content_html 保持可读（GET /full 双版本同在），
  revised_note / 批注 / lumi_notes 锚点一字不动；切换与回退都经
  DELETE revision 的既有路径可逆。

per-user：候选行与剪藏同库（RoutingDatabase），A 的候选对 B 不可见。
"""

import uuid as _uuid
from collections.abc import Awaitable, Callable
from html.parser import HTMLParser
from typing import Any

from lumirss.article_extract import extract_article
from lumirss.article_sanitize import sanitize_html
from lumirss.clip_fetch import fetch_extract_sanitize
from lumirss.storage import Database
from lumirss.util import utc_now

PreviewChars = 200

Fetcher = Callable[[str], Awaitable[Any]]

_DROP_WITH_CONTENT = frozenset(
    {"script", "style", "noscript", "template", "iframe", "svg", "form"}
)
_DROP_ALSO = frozenset({"nav", "header", "footer", "aside"})


class _FulltextParser(HTMLParser):
    """保真兜底：丢脚本/样式/明显非正文容器，其余结构原样序列化。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):  # noqa: D401 — parser callback
        lowered = tag.lower()
        if lowered in _DROP_WITH_CONTENT:
            if lowered not in ("meta", "link", "br", "img", "hr", "input"):
                self._skip_depth += 1
            return
        if self._skip_depth > 0:
            return
        if lowered in ("html", "head", "body"):
            return
        if lowered in _DROP_ALSO:
            return
        rendered = " ".join(f'{k}="{v}"' for k, v in attrs if k)
        self._out.append(f"<{lowered}{(' ' + rendered) if rendered else ''}>")

    def handle_startendtag(self, tag, attrs):  # noqa: D401 — parser callback
        lowered = tag.lower()
        if lowered in _DROP_WITH_CONTENT or lowered in _DROP_ALSO:
            return
        if self._skip_depth > 0:
            return
        if lowered in ("html", "head", "body"):
            return
        rendered = " ".join(f'{k}="{v}"' for k, v in attrs if k)
        self._out.append(f"<{lowered}{(' ' + rendered) if rendered else ''}/>")

    def handle_endtag(self, tag):  # noqa: D401 — parser callback
        lowered = tag.lower()
        if lowered in _DROP_WITH_CONTENT:
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if self._skip_depth > 0 or lowered in ("html", "head", "body"):
            return
        if lowered in _DROP_ALSO:
            return
        self._out.append(f"</{lowered}>")

    def handle_data(self, data):  # noqa: D401 — parser callback
        if self._skip_depth > 0:
            return
        self._out.append(data)

    def result(self) -> str:
        return "".join(self._out)


def fulltext_html(raw_html: str) -> str:
    """策略 B：保真全文（丢脚本/样式/导航容器，不评分、不裁剪正文）。"""
    parser = _FulltextParser()
    try:
        parser.feed(raw_html)
        parser.close()
    except Exception:  # noqa: BLE001 — 兜底策略宁可输出部分，也不中断
        pass
    return parser.result()


def _strategy_result(
    strategy: str, raw_html: str, base_url: str
) -> dict[str, Any]:
    """同一份原始 HTML 的两种提取；sanitize 是共同存储边界。"""
    if strategy == "article":
        article = extract_article(raw_html)
        title = article.title
        clean_html = sanitize_html(article.content_html, base_url=base_url)
    else:
        title = ""
        clean_html = sanitize_html(fulltext_html(raw_html), base_url=base_url)
    from lumirss.adapters.freshrss import AdapterError, html_to_text

    try:
        text = html_to_text(clean_html)
    except AdapterError:
        text = ""
    return {
        "strategy": strategy,
        "title": (title or "")[:500],
        "content_html": clean_html,
        "content_text": text[:512 * 1024],
    }


class ExtractCompareService:
    """候选对照（抓取可注入：默认走真实有界管线；测试注入假抓取）。"""

    def __init__(self, db: Database, *, fetcher: Fetcher | None = None) -> None:
        self._db = db
        self._fetcher: Fetcher = fetcher or fetch_extract_sanitize

    async def compare(self, clip_item_uuid: str, *, base_url: str) -> dict[str, Any]:
        """抓取一次 → 两种候选 → 存库（chosen=0）→ 返回对照预览。"""
        row = await self._clip_row(clip_item_uuid)
        if row is None:
            from lumirss.library_clips import ClipNotFound

            raise ClipNotFound()
        page = await self._fetcher(row["url"])
        raw_html = getattr(page, "html", None)
        if raw_html is None:
            raise ValueError("fetcher 未返回 FetchedPage。")
        final_url = getattr(page, "final_url", base_url) or base_url
        await self._db.migrate()
        now = utc_now()
        stored: list[dict[str, Any]] = []
        for strategy in ("article", "fulltext"):
            result = _strategy_result(strategy, raw_html, final_url)
            candidate_id = str(_uuid.uuid4())
            await self._db.execute(
                "INSERT INTO clip_extract_candidates (id, clip_item_uuid, strategy, title, content_html, content_text, char_count, chosen, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)",
                (
                    candidate_id, clip_item_uuid, strategy, result["title"],
                    result["content_html"], result["content_text"],
                    len(result["content_text"]), now,
                ),
            )
            stored.append(
                {
                    "id": candidate_id,
                    "strategy": strategy,
                    "title": result["title"],
                    "charCount": len(result["content_text"]),
                    "preview": result["content_text"][:PreviewChars],
                    "chosen": False,
                }
            )
        return {
            "clipRef": f"library:{clip_item_uuid}",
            "fetchedAt": now,
            "candidates": stored,
            "honestyNote": (
                "两种候选来自同一次抓取；选择只切换展示版本，"
                "原版保持可读，笔记与批注锚点不会被改写。"
            ),
        }

    async def last_compare(self, clip_item_uuid: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._clip_row(clip_item_uuid)
        if row is None:
            from lumirss.library_clips import ClipNotFound

            raise ClipNotFound()
        rounds = await self._db.fetch_all(
            "SELECT id, strategy, title, char_count, chosen, created_at"
            " FROM clip_extract_candidates WHERE clip_item_uuid = ?"
            " ORDER BY created_at DESC, id DESC LIMIT 2",
            (clip_item_uuid,),
        )
        if not rounds:
            return None
        return {
            "clipRef": f"library:{clip_item_uuid}",
            "candidates": [
                {
                    "id": str(r["id"]),
                    "strategy": str(r["strategy"]),
                    "title": str(r["title"]),
                    "charCount": int(r["char_count"]),
                    "preview": "",
                    "chosen": bool(r["chosen"]),
                }
                for r in reversed(rounds)
            ],
        }

    async def choose(self, clip_item_uuid: str, candidate_id: str) -> dict[str, Any]:
        """应用候选到修订槽（不碰原始版本、不碰笔记锚点）。"""
        row = await self._db.fetch_one(
            "SELECT content_html, content_text FROM clip_extract_candidates"
            " WHERE id = ? AND clip_item_uuid = ?",
            (candidate_id, clip_item_uuid),
        )
        if row is None:
            from lumirss.library_clips import ClipNotFound

            raise ClipNotFound()
        await self._db.migrate()
        now = utc_now()

        def _tx(conn: Any) -> None:
            conn.execute(
                "UPDATE clip_extract_candidates SET chosen = 0 WHERE clip_item_uuid = ?",
                (clip_item_uuid,),
            )
            conn.execute(
                "UPDATE clip_extract_candidates SET chosen = 1 WHERE id = ?",
                (candidate_id,),
            )
            conn.execute(
                "UPDATE library_clips SET revised_content_html = ?, revised_at = ?"
                " WHERE item_uuid = ?",
                (str(row["content_html"]), now, clip_item_uuid),
            )

        from lumirss.db_tx import transaction

        await transaction(self._db, _tx)
        return {
            "clipRef": f"library:{clip_item_uuid}",
            "chosenId": candidate_id,
            "appliedAt": now,
            "note": (
                "已切换展示版本（修订槽）；原始版本保持可读，"
                "笔记与批注锚点未改动，可用 DELETE revision 回退。"
            ),
        }

    async def _clip_row(self, clip_item_uuid: str) -> Any:
        await self._db.migrate()
        return await self._db.fetch_one(
            "SELECT item_uuid, url FROM library_clips WHERE item_uuid = ?",
            (clip_item_uuid,),
        )
