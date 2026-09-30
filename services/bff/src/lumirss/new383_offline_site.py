"""NEW-383 HTML 资料集离线站点 —— 允许保存的文章 + 索引 → 无需服务端
的静态资料集（zip）。包内链接自洽，不含任何私人未选内容。

口径（与 FIX-326 可移植打包同族）：

- 输入：用户显式选中的书目记录（new381_bib_records）与/或剪藏
  （library_clips），≤200 条；只有选中的条目进包——未选内容连
  元数据都不出现；
- 文章页：剪藏正文先过既有 DOMPurify 边界的 BFF 侧实现
  （article_sanitize：allow-list 标签/属性、事件处理器无条件拒绝、
  危险 scheme 拒绝）；书目页渲染元数据（无正文）；
- 链接自洽终检：重写后再扫全部 href/src——``..``/绝对路径/file:/
  其他 scheme 即 violation（结果随台账如实落库）；包外 http(s) 链接
  允许保留为普通外链（记入 externalLinks，带 rel 保护）；
- zip 即时组装返回（index.html + items/*.html + manifest.json），
  台账只存选中引用、违规与摘要，不囤二进制；下载按台账从当前数据
  重装（条目已删除时如实列出缺失）。

per-user：选中面是 member 自己的库，A 的包对 B 不可见。
"""

import hashlib
import io
import json
import re
import uuid as _uuid
import zipfile
from typing import Any

from lumirss.article_sanitize import sanitize_html
from lumirss.new381_bib import BibStore
from lumirss.storage import Database
from lumirss.util import utc_now

MAX_ITEMS = 200
_SLUG_RE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff]+")
_EXTERNAL_RE = re.compile(r"^https?://", re.IGNORECASE)
_VIOLATION_RE = re.compile(r"^(?:\.\.?/|[A-Za-z]:[\\/]|file:)", re.IGNORECASE)
_ATTR_SRC_RE = re.compile(
    r"\b(href|src)=\"([^\"]+)\"", re.IGNORECASE
)


class OfflineSiteInvalid(ValueError):
    """离线站点请求非法（映射 400）。"""


def _slug(text: str, index: int) -> str:
    base = _SLUG_RE.sub("-", text.strip())[:60].strip("-")
    return f"{index:03d}-{base or 'item'}"


def _page(title: str, body_html: str) -> str:
    return (
        "<!doctype html>\n"
        '<html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_esc(title)}</title>"
        "<style>body{font-family:system-ui,sans-serif;margin:2rem auto;"
        "max-width:46rem;padding:0 1rem;line-height:1.7;color:#222}"
        "header a{display:block;margin-bottom:1.5rem}</style></head>"
        '<body><header><a href="../index.html">← 返回目录</a></header>'
        f"<article>{body_html}</article></body></html>\n"
    )


def _esc(text: str) -> str:
    import html

    return html.escape(text, quote=True)


class OfflineSiteBuilder:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def build(
        self, bib_ids: list[str], clip_uuids: list[str]
    ) -> dict[str, Any]:
        """组装离线站点 → {manifest, files: {arcname: bytes}}（零写入）。"""
        await self._db.migrate()
        bib_ids = [str(ref) for ref in bib_ids if str(ref).strip()]
        clip_uuids = [str(ref) for ref in clip_uuids if str(ref).strip()]
        total = len(bib_ids) + len(clip_uuids)
        if total == 0:
            raise OfflineSiteInvalid("请至少选择一条资料。")
        if total > MAX_ITEMS:
            raise OfflineSiteInvalid(f"一次最多打包 {MAX_ITEMS} 条资料。")

        store = BibStore(self._db)
        known_bib = await store.get_records_by_ids(bib_ids)
        known_ids = {record["id"] for record in known_bib}
        missing_bib = [ref for ref in bib_ids if ref not in known_ids]
        clip_rows = await self._fetch_clips(clip_uuids)
        known_clip = {str(row["item_uuid"]) for row in clip_rows}
        missing_clips = [ref for ref in clip_uuids if ref not in known_clip]

        files: dict[str, bytes] = {}
        pages: list[dict[str, str]] = []
        violations: list[dict[str, str]] = []
        external_links: set[str] = set()

        for index, record in enumerate(known_bib, start=1):
            slug = _slug(record["title"], index)
            body = self._bib_body(record)
            body = self._scan(body, violations, external_links, slug)
            files[f"items/{slug}.html"] = _page(record["title"], body).encode("utf-8")
            pages.append(
                {
                    "kind": "bib",
                    "ref": record["id"],
                    "title": record["title"],
                    "path": f"items/{slug}.html",
                }
            )
        for index, row in enumerate(clip_rows, start=len(known_bib) + 1):
            slug = _slug(str(row["title"]), index)
            clean_html = self._scan(
                sanitize_html(str(row["content_html"])),
                violations,
                external_links,
                slug,
            )
            body = (
                f"<h1>{_esc(str(row['title']))}</h1>"
                f"<p class=meta>剪藏于 {_esc(str(row['created_at']))} · "
                f"原文 {_esc(str(row['url']))}</p>\n{clean_html}"
            )
            files[f"items/{slug}.html"] = _page(str(row["title"]), body).encode("utf-8")
            pages.append(
                {
                    "kind": "clip",
                    "ref": str(row["item_uuid"]),
                    "title": str(row["title"]),
                    "path": f"items/{slug}.html",
                }
            )

        index_body = "<h1>离线资料集</h1><ul>" + "".join(
            f'<li><a href="{_esc(page["path"])}">{_esc(page["title"])}</a>'
            f"（{page['kind']}）</li>"
            for page in pages
        ) + "</ul>"
        files["index.html"] = _page("离线资料集", index_body).encode("utf-8")
        manifest = {
            "generator": "LumiRSS offline-site",
            "generatedAt": utc_now(),
            "itemCount": len(pages),
            "items": pages,
        }
        files["manifest.json"] = json.dumps(
            manifest, ensure_ascii=False, indent=2
        ).encode("utf-8")

        missing = missing_bib + missing_clips
        result = {
            "manifest": {
                "itemCount": len(pages),
                "items": pages,
                "violations": violations,
                "violationCount": len(violations),
                "externalLinks": sorted(external_links),
                "missing": missing,
                "generatedAt": utc_now(),
            },
            "files": files,
        }
        digest = hashlib.sha256()
        for name in sorted(files):
            digest.update(name.encode("utf-8"))
            digest.update(files[name])
        result["manifest"]["sha256"] = digest.hexdigest()
        return result

    async def persist(self, manifest: dict[str, Any]) -> str:
        await self._db.migrate()
        site_id = f"offsite-{_uuid.uuid4().hex[:12]}"
        await self._db.execute(
            "INSERT INTO new383_offline_sites"
            " (id, item_refs_json, item_count, violation_count, violations_json,"
            " external_links_json, sha256, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                site_id,
                json.dumps(
                    [page["ref"] for page in manifest["items"]], ensure_ascii=False
                ),
                int(manifest["itemCount"]),
                int(manifest["violationCount"]),
                json.dumps(manifest["violations"], ensure_ascii=False),
                json.dumps(manifest["externalLinks"], ensure_ascii=False),
                str(manifest["sha256"]),
                utc_now(),
            ),
        )
        return site_id

    async def list_sites(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, item_refs_json, item_count, violation_count, violations_json,"
            " external_links_json, sha256, created_at FROM new383_offline_sites"
            " ORDER BY created_at DESC, id ASC LIMIT 100"
        )
        import json

        return [
            {
                "id": str(row["id"]),
                "itemRefs": json.loads(str(row["item_refs_json"])),
                "itemCount": int(row["item_count"]),
                "violationCount": int(row["violation_count"]),
                "violations": json.loads(str(row["violations_json"])),
                "externalLinks": json.loads(str(row["external_links_json"])),
                "sha256": str(row["sha256"]),
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]

    async def get_site(self, site_id: str) -> dict[str, Any] | None:
        sites = await self.list_sites()
        for site in sites:
            if site["id"] == site_id:
                return site
        return None

    async def rebuild(self, site_id: str) -> dict[str, Any] | None:
        """按台账从当前数据重装 zip；条目已删除的如实列入 missing。"""
        site = await self.get_site(site_id)
        if site is None:
            return None
        refs = [str(ref) for ref in site["itemRefs"]]
        built = await self.build(
            [ref for ref in refs if ref.startswith("bib-")],
            [ref for ref in refs if not ref.startswith("bib-")],
        )
        built["manifest"]["missing"] = sorted(set(built["manifest"]["missing"]))
        return built

    async def _fetch_clips(self, clip_uuids: list[str]) -> list[Any]:
        rows = await self._db.fetch_all(
            "SELECT item_uuid, url, title, content_html, content_text, created_at"
            " FROM library_clips ORDER BY created_at DESC, item_uuid ASC LIMIT 2000"
        )
        wanted = set(clip_uuids)
        return [row for row in rows if str(row["item_uuid"]) in wanted]

    def _bib_body(self, record: dict[str, Any]) -> str:
        parts = [f"<h1>{_esc(record['title'])}</h1>"]
        if record["creators"]:
            parts.append(f"<p>{_esc('；'.join(record['creators']))}</p>")
        meta = " · ".join(
            bit
            for bit in (record["pubYear"], record["publication"], record["publisher"])
            if bit
        )
        if meta:
            parts.append(f"<p>{_esc(meta)}</p>")
        if record["doi"]:
            parts.append(f"<p>DOI: {_esc(record['doi'])}</p>")
        if record["url"]:
            parts.append(
                f'<p>原文: <a href="{_esc(record["url"])}">{_esc(record["url"])}</a></p>'
            )
        if record["tags"]:
            parts.append(
                "<p>"
                + " ".join(f"<code>{_esc(tag)}</code>" for tag in record["tags"])
                + "</p>"
            )
        if record["abstract"]:
            parts.append(f"<blockquote>{_esc(record['abstract'])}</blockquote>")
        return "\n".join(parts)

    def _scan(
        self,
        html: str,
        violations: list[dict[str, str]],
        external: set[str],
        slug: str,
    ) -> str:
        """终检 + 中和：越界/不可解析目标从链接属性中移除（保留文字），
        违规如实记账；http(s) 外链保留为普通外链（带 rel 保护由净化器
        写入）；包内相对目标原样保留。返回中和后的 HTML。"""

        def _replace(match: re.Match[str]) -> str:
            attr, target = match.group(1).lower(), match.group(2)
            if target.startswith(("#", "mailto:", "../index.html", "items/",
                                  "index.html")):
                return match.group(0)
            if _VIOLATION_RE.match(target):
                violations.append({"slug": slug, "target": target[:500]})
                return f'{attr}="#"'
            if _EXTERNAL_RE.match(target):
                external.add(target[:1000])
                return match.group(0)
            # 其余相对目标（裸文件名等）在包内无法解析 → 不自洽，移除
            violations.append({"slug": slug, "target": f"unresolved:{target[:480]}"})
            return f'{attr}="#"'

        return _ATTR_SRC_RE.sub(_replace, html)


def assemble_zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            archive.writestr(name, files[name])
    return buffer.getvalue()
