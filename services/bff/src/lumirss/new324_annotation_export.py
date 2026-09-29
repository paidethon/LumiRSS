"""NEW-324 阅读批注 Markdown 输出 —— 本人批注 → 带来源与稳定锚点的
Markdown 文件内容（用户自行保存入库）。

口径：

- 绝不代写任何文件（尤其绝不写 Vault）：路由返回 {filename, content}，
  保存动作由用户自己完成；
- 来源：文章标题 / 订阅源 / 原文 URL 来自本人 search_entries 投影
  （纯本地读，零上游网络）；投影未同步的文章如仍有批注，来源栏如实
  标「（投影中暂无该文章）」；两者皆无 → 进 unresolvedRefs 诚实列出；
- 稳定锚点：每条批注带 Obsidian 块 id ``^lumi-<paraId>``（与导出交接
  N134 同一形状）+ 服务端等价回跳链接 ``/reader?entry=…&para=…``；
- 台账（annotation_markdown_exports）只记录发生过什么，可追溯重导。

per-user：批注与投影都在各自用户库——A 的导出绝不含 B 的批注。
"""

import json
import uuid as _uuid
from typing import Any

from lumirss.annotation_store import AnnotationStore
from lumirss.storage import Database
from lumirss.util import utc_now

MAX_ENTRY_REFS = 50
_MAX_EXPORTS_LISTED = 50
_MAX_NOTE_LINES = 40


class AnnotationExportInvalid(ValueError):
    """导出请求非法（映射 400）。"""


def _para_id_of(annotation: dict[str, Any]) -> str:
    anchor = annotation.get("anchor")
    if isinstance(anchor, dict):
        return str(anchor.get("paraId") or "").strip()
    return ""


def _entry_header(entry: dict[str, Any] | None, entry_ref: str) -> list[str]:
    if entry is None:
        return [
            f"## {entry_ref}",
            "",
            "- 来源：（投影中暂无该文章，来源信息未同步）",
        ]
    lines = [f"## {entry['title'] or entry_ref}", ""]
    source = entry.get("feed_title") or ""
    if source:
        lines.append(f"- 来源：{source}")
    url = entry.get("url") or ""
    if url:
        lines.append(f"- 原文：{url}")
    lines.append(f"- 在 LumiRSS 中查看：/reader?entry={entry_ref}")
    return lines


def _render_annotation(annotation: dict[str, Any]) -> list[str]:
    quote = str(annotation.get("excerpt") or "").strip()
    note = str(annotation.get("note") or "").strip()
    para_id = _para_id_of(annotation)
    color = str(annotation.get("color") or "")
    lines = [""]
    if quote:
        lines.append(f"> {quote}")
        lines.append(">")
    if note:
        for note_line in note.splitlines()[:_MAX_NOTE_LINES]:
            lines.append(note_line)
    if para_id:
        lines.append(f"^lumi-{para_id}")
        lines.append("")
        lines.append(f"回跳：/reader?entry={annotation.get('entryRef', '')}&para={para_id}")
    else:
        lines.append("")
        lines.append("（该批注无段落锚点）")
    if color:
        lines.append(f"标注颜色：{color}")
    lines.append("")
    lines.append("---")
    return lines


def render_markdown(
    entries: list[tuple[dict[str, Any] | None, list[dict[str, Any]], str]],
    *,
    generated_at: str,
) -> str:
    """(entry, annotations, entry_ref) 三元组 → 完整 Markdown 文本。"""
    total_annotations = sum(len(annotations) for _e, annotations, _r in entries)
    lines = [
        "# LumiRSS 阅读批注导出",
        "",
        f"- 导出时间：{generated_at}",
        f"- 文章数：{len(entries)} · 批注数：{total_annotations}",
        "",
        "> 由 LumiRSS 生成；锚点 ^lumi-<paraId> 可在 LumiRSS 中回跳定位。",
        "",
    ]
    for entry, annotations, entry_ref in entries:
        lines.extend(_entry_header(entry, entry_ref))
        if not annotations:
            lines.extend(["", "（该文章暂无批注）", "", "---"])
            continue
        for annotation in annotations:
            lines.extend(_render_annotation(annotation))
    return "\n".join(lines).rstrip() + "\n"


def export_filename(now: str | None = None) -> str:
    """建议文件名（与 N135 命名策略同款时间戳后缀，永不覆盖旧文件）。"""
    from lumirss.obsidian_handoff import _timestamp_suffix

    stamp = _timestamp_suffix(now)
    return f"LumiRSS-批注-{stamp}.md"


class AnnotationMarkdownExporter:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def export(self, entry_refs: list[str]) -> dict[str, Any]:
        await self._db.migrate()
        if not isinstance(entry_refs, list):
            raise AnnotationExportInvalid("entryRefs 必须是字符串数组。")
        ordered: list[str] = []
        for ref in entry_refs:
            clean = str(ref).strip()
            if clean and clean not in ordered:
                ordered.append(clean)
        if not ordered:
            raise AnnotationExportInvalid("entryRefs 不能为空。")
        if len(ordered) > MAX_ENTRY_REFS:
            raise AnnotationExportInvalid(
                f"一次最多导出 {MAX_ENTRY_REFS} 篇文章的批注。"
            )
        store = AnnotationStore(self._db)
        sections: list[tuple[dict[str, Any] | None, list[dict[str, Any]], str]] = []
        unresolved: list[str] = []
        annotation_total = 0
        for ref in ordered:
            # search_entries 的 entry_ref 不带域前缀；接受带 rss: 前缀的
            # 书写（与回跳链接同一形状），查找前剥掉。
            bare_ref = ref[4:] if ref.startswith("rss:") else ref
            row = await self._db.fetch_one(
                "SELECT title, feed_title, url FROM search_entries WHERE entry_ref = ?",
                (bare_ref,),
            )
            entry = (
                {
                    "title": str(row["title"] or ""),
                    "feed_title": str(row["feed_title"] or ""),
                    "url": str(row["url"] or ""),
                }
                if row is not None
                else None
            )
            annotations = await store.list_for_entry(ref)
            if entry is None and not annotations:
                unresolved.append(ref)
                continue
            annotation_total += len(annotations)
            sections.append((entry, annotations, ref))
        if not sections:
            raise AnnotationExportInvalid(
                "所选文章在本人资料中都不存在（既无投影也无批注）。"
            )
        generated_at = utc_now()
        filename = export_filename(generated_at)
        content = render_markdown(sections, generated_at=generated_at)
        export_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO annotation_markdown_exports (id, entry_refs_json, entry_count, annotation_count, filename, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                export_id,
                json.dumps([ref for _e, _a, ref in sections], ensure_ascii=False),
                len(sections),
                annotation_total,
                filename,
                generated_at,
            ),
        )
        return {
            "id": export_id,
            "filename": filename,
            "content": content,
            "entryCount": len(sections),
            "annotationCount": annotation_total,
            "unresolvedRefs": unresolved,
            "generatedAt": generated_at,
            "honestyNote": "Lumi 不代写文件：请自行把上面的 Markdown 保存进你的资料库；源 Vault 保持只读。",
        }

    async def history(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, entry_refs_json, entry_count, annotation_count, filename, created_at"
            " FROM annotation_markdown_exports ORDER BY created_at DESC, id DESC LIMIT ?",
            (_MAX_EXPORTS_LISTED,),
        )
        items: list[dict[str, Any]] = []
        for row in rows:
            try:
                refs = json.loads(str(row["entry_refs_json"] or "[]"))
            except json.JSONDecodeError:
                refs = []
            items.append(
                {
                    "id": str(row["id"]),
                    "entryRefs": refs if isinstance(refs, list) else [],
                    "entryCount": int(row["entry_count"]),
                    "annotationCount": int(row["annotation_count"]),
                    "filename": str(row["filename"]),
                    "createdAt": str(row["created_at"]),
                }
            )
        return items
