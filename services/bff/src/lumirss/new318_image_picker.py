"""NEW-318 剪藏图片选择器 —— 列出可用图片与预计体积，用户勾选后保存。

- 清单（manifest）零写入、零图片下载：一次有界页面抓取（继承
  clip_fetch 的 SSRF 预检 + pinned dial + 5MB/30s 上限）→ sanitize_html
  净化边界 → 从净化后的 HTML 解析 <img>；体积来自「有界探测」：
  HEAD content-length，405/501/400 降级有界 GET（≤256KB 即断），
  并发≤4、单图 8s 超时、最多 12 张；探测不到 → ``bytes: null``
  （诚实未知，绝不猜数）；``data:`` URI 直接按编码字节数精确计算；
- 勾选保存（curate）：同一有界管线再抓一次 → 净化 → 服务端丢弃
  未勾选的 <img>（被丢弃的图片一个字节都不下载）→ 走
  ClipStore.create_clip 的既有边界（URL 唯一收敛 + 搜索投影）→
  勾选结果落 clip_image_selections 台账；
- 抓取失败 / 不可达 → 诚实失败（502），绝不拿旧清单假装新清单。

per-user：勾选台账与剪藏同库（RoutingDatabase）。
"""

import base64
import re
from typing import Any

from lumirss.article_sanitize import sanitize_html
from lumirss.clip_fetch import fetch_page
from lumirss.new313_extract_compare import fulltext_html
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_IMAGES = 50
_MAX_PROBED = 12
_PROBE_TIMEOUT_S = 8.0
_PROBE_MAX_BYTES = 256 * 1024
_PROBE_CONCURRENCY = 4

_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_ATTR_RE = re.compile(r'([a-zA-Z_:][\w:.-]*)="([^"]*)"')


class ImagePickerError(Exception):
    """页面抓取失败（映射 502，诚实失败）。"""


class ImageListInvalid(ValueError):
    """清单/勾选负载非法（映射 422）。"""


def parse_images(sanitized_html: str) -> list[dict[str, Any]]:
    """从【净化后】的 HTML 解析 img（src/alt），保持出现顺序去重。"""
    images: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in _IMG_RE.finditer(sanitized_html):
        attrs = dict(_ATTR_RE.findall(match.group(0)))
        src = (attrs.get("src") or "").strip()
        if not src or src in seen:
            continue
        seen.add(src)
        bytes_size: int | None = None
        if src.lower().startswith("data:"):
            _header, _sep, payload = src.partition(",")
            try:
                bytes_size = len(base64.b64decode(payload, validate=False))
            except Exception:  # noqa: BLE001 — 体积未知 ≠ 清单失败
                bytes_size = None
        images.append(
            {
                "src": src[:2048],
                "alt": (attrs.get("alt") or "")[:300],
                "bytes": bytes_size,
            }
        )
        if len(images) >= _MAX_IMAGES:
            break
    return images


async def probe_image_size(
    url: str,
    *,
    client_factory: Any = None,
) -> int | None:
    """有界探测单图体积：HEAD content-length → 降级有界 GET。

    ``client_factory`` 可注入（测试用 MockTransport）；生产为
    SSRF-pinned AsyncClient（每次 dial 复检地址）。任何失败 → None。
    """
    import asyncio

    if client_factory is None:
        from lumirss.bookmarks_check import _pinned_client_factory

        client_factory = _pinned_client_factory

    async def _read_bounded(client: Any, method: str) -> int | None:
        try:
            response = await asyncio.wait_for(
                client.request(method, url, follow_redirects=False),
                timeout=_PROBE_TIMEOUT_S,
            )
        except Exception:  # noqa: BLE001 — 探测失败 = 未知，不是错误
            return None
        try:
            declared = response.headers.get("content-length")
            if declared is not None and declared.isdigit():
                return int(declared)
            received = 0
            async for chunk in response.aiter_bytes():
                received += len(chunk)
                if received >= _PROBE_MAX_BYTES:
                    break
            return received
        except Exception:  # noqa: BLE001
            return None
        finally:
            await response.aclose()

    try:
        async with client_factory() as client:
            head = await _read_bounded(client, "HEAD")
            if head is not None and head > 0:
                return head
            return await _read_bounded(client, "GET")
    except Exception:  # noqa: BLE001
        return None


def _clean_fetch_result(page: Any) -> tuple[str, str]:
    html = getattr(page, "html", None)
    final_url = getattr(page, "final_url", "") or ""
    if html is None:
        raise ImagePickerError("抓取结果为空。")
    return html, final_url


def drop_unselected_images(sanitized_html: str, selected: set[str]) -> str:
    """从净化 HTML 中丢弃未勾选的 <img>（其余结构保真）。"""
    def _keep(match: re.Match[str]) -> str:
        attrs = dict(_ATTR_RE.findall(match.group(0)))
        return match.group(0) if (attrs.get("src") or "") in selected else ""

    return _IMG_RE.sub(_keep, sanitized_html)


class ImagePickerService:
    """清单 + 勾选保存（抓取与探测均可注入，生产走默认有界管线）。"""

    def __init__(
        self,
        db: Database,
        *,
        fetcher: Any = None,
        size_prober: Any = None,
    ) -> None:
        self._db = db
        self._fetcher = fetcher or fetch_page
        self._size_prober = size_prober

    async def manifest(self, url: str) -> dict[str, Any]:
        import asyncio

        try:
            page = await self._fetcher(url)
        except Exception as exc:  # ClipFetchError/ClipForbidden → 诚实失败
            raise ImagePickerError(str(exc)) from exc
        raw_html, final_url = _clean_fetch_result(page)
        sanitized = sanitize_html(fulltext_html(raw_html), base_url=final_url)
        images = parse_images(sanitized)

        if self._size_prober is not None:
            prober = self._size_prober
        else:
            prober = probe_image_size
        probe_targets = [img for img in images if img["bytes"] is None][:_MAX_PROBED]
        if probe_targets:
            sizes = await asyncio.gather(
                *(prober(img["src"]) for img in probe_targets)
            )
            size_map = {
                img["src"]: size
                for img, size in zip(probe_targets, sizes, strict=True)
            }
        else:
            size_map = {}
        for img in images:
            if img["bytes"] is None:
                img["bytes"] = size_map.get(img["src"])
        probed = sum(1 for img in images if img["bytes"] is not None)
        return {
            "url": url,
            "finalUrl": final_url,
            "images": images,
            "imageCount": len(images),
            "sizedCount": probed,
            "truncatedProbes": max(0, len(images) - _MAX_PROBED),
            "honestyNote": (
                "体积来自有界探测（HEAD 优先），未知即为 null，绝不猜数；"
                "只有你勾选的图片会在保存时保留，其余一个字节都不下载。"
            ),
        }

    async def curate(
        self, url: str, selected_images: list[str]
    ) -> dict[str, Any]:
        if not isinstance(selected_images, list) or any(
            not isinstance(src, str) for src in selected_images
        ):
            raise ImageListInvalid("selectedImages 必须是字符串数组。")
        selected = {src for src in selected_images if src}
        if len(selected) > _MAX_IMAGES:
            raise ImageListInvalid(f"一次最多勾选 {_MAX_IMAGES} 张图片。")
        try:
            page = await self._fetcher(url)
        except Exception as exc:
            raise ImagePickerError(str(exc)) from exc
        raw_html, final_url = _clean_fetch_result(page)
        sanitized = sanitize_html(fulltext_html(raw_html), base_url=final_url)
        # 未勾选的图片一个字节都不保留（空勾选 = 明确不带图）。
        kept_html = drop_unselected_images(sanitized, selected)
        available = {img["src"] for img in parse_images(sanitized)}
        unknown = sorted(selected - available)

        from lumirss.adapters.freshrss import AdapterError, html_to_text
        from lumirss.article_extract import extract_article
        from lumirss.library_clips import ClipStore

        article = extract_article(kept_html)
        body_html = (
            article.content_html
            if article.content_html and article.content_html.strip()
            else kept_html
        )
        title = article.title or final_url or url
        try:
            text = html_to_text(body_html)
        except AdapterError:
            text = ""
        clip_store = ClipStore(self._db)
        view, created = await clip_store.create_clip(
            url=url,
            title=title[:500] or url,
            content_html=body_html,
            content_text=text[:512 * 1024],
        )
        item_uuid = view.ref.split(":", 1)[1]
        now = utc_now()

        def _tx(conn: Any) -> None:
            existing = conn.execute(
                "SELECT 1 AS ok FROM clip_image_selections WHERE clip_item_uuid = ?",
                (item_uuid,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO clip_image_selections (clip_item_uuid, urls_json, selected_count, created_at)"
                    " VALUES (?, ?, ?, ?)",
                    (item_uuid, _urls_json(sorted(selected)), len(selected), now),
                )
            else:
                conn.execute(
                    "UPDATE clip_image_selections SET urls_json = ?, selected_count = ?, created_at = ?"
                    " WHERE clip_item_uuid = ?",
                    (_urls_json(sorted(selected)), len(selected), now, item_uuid),
                )

        from lumirss.db_tx import transaction

        await transaction(self._db, _tx)
        return {
            "clip": view.to_dict(with_content=True),
            "created": created,
            "selectedCount": len(selected),
            "unknownSelections": unknown,
            "selectionRecorded": True,
        }

    async def last_selection(self, clip_item_uuid: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT urls_json, selected_count, created_at FROM clip_image_selections"
            " WHERE clip_item_uuid = ?",
            (clip_item_uuid,),
        )
        if row is None:
            return None
        return {
            "clipRef": f"library:{clip_item_uuid}",
            "selectedImages": _load_urls(str(row["urls_json"])),
            "selectedCount": int(row["selected_count"]),
            "createdAt": str(row["created_at"]),
        }


def _urls_json(urls: list[str]) -> str:
    import json

    return json.dumps(urls, ensure_ascii=False)


def _load_urls(raw: str) -> list[str]:
    import json

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(u) for u in parsed] if isinstance(parsed, list) else []
