"""P16 导出到 Obsidian 交接（handoff）— 组装 + 渲染 + URI 预算裁决。

流程（一个入口 :func:`prepare_handoff`）：

1. 由 entryRef 解析文章（BFF adapter，读路径与 entries 路由同源）；
2. 收集该文章的批注（AnnotationStore 读 API，每用户库）——每条批注
   生成服务端等价的 buildParaLink 定位链接（``/reader?entry=<ref>&
   para=<anchorId>``，无凭据）；
3. 按用户模板渲染 Markdown（obsidian_template，纯替换）；
4. 构造官方 ``obsidian://new`` URI（obsidian_uri，8000 字符预算）。

裁决结果（诚实交接语义）：

- ``mode='uri'``  → 前端 ``window.location = uri`` 打开用户的 Obsidian，
  UI 文案必须是「已打开 Obsidian（请在 Obsidian 确认保存）」——绝不
  说「已写入」：Lumi 没写 Vault（ADR 0004），写入只发生在用户于
  Obsidian 中确认保存时；
- ``mode='file'`` → 内容超出 URI 预算（或 vault 未配置成 URI）→ 退回
  「下载 .md + 剪贴板」双通道，UI 说明实际走了哪条路。
"""

import re
from dataclasses import dataclass
from typing import Any

from lumirss.annotation_store import AnnotationStore
from lumirss.obsidian_template import (
    DEFAULT_TEMPLATE,
    TemplateRenderResult,
    render_template,
)
from lumirss.obsidian_uri import build_obsidian_new_uri

_MAX_FILENAME_STEM = 80

_SAFE_FILENAME_RE = re.compile(r"[/\\:*?\"<>|]")

# fixture 预览（无 entryRef 时的模板预览样例；中文 + 全字段缺失路径）
FIXTURE_CONTEXT: dict[str, Any] = {
    "title": "示例文章：LumiRSS 导出到 Obsidian",
    "url": "https://example.com/lumirss-export",
    "source": "示例订阅源",
    "date": "2026-09-23",
    "published": "2026-09-23T08:00:00Z",
    "content": "这是示例正文（模板预览夹具文本），用于检查变量排布是否合意。",
    "annotations": [
        {
            "quote": "这是一条示例批注摘录。",
            "link": "/reader?entry=fixture.example&para=abcd1234-1",
        }
    ],
}


@dataclass(frozen=True)
class HandoffPrepared:
    mode: str  # 'uri' | 'file'
    uri: str | None
    filename: str
    content: str
    unknown_vars: list[str]
    device_label: str
    reason: str | None  # 'tooLong' | None


def _entry_date(detail: Any) -> tuple[str, str]:
    """(展示日期, 原始 published)；发布时间缺失回退收录时间（诚实）。"""
    published = getattr(detail, "publishedAt", None) or ""
    if published:
        return published[:10], published
    crawled = getattr(detail, "crawledAt", None) or ""
    return (crawled[:10] if crawled else ""), published


def build_export_context(detail: Any, annotations: list[dict[str, Any]]) -> dict[str, Any]:
    """Template context from one EntryDetail + its annotations."""
    date, published = _entry_date(detail)
    rendered_annotations = []
    for annotation in annotations:
        anchor = annotation.get("anchor")
        para = ""
        if isinstance(anchor, dict):
            para = str(anchor.get("paraId") or "")
        entry_ref = str(annotation.get("entry_ref") or getattr(detail, "entryRef", ""))
        link = f"/reader?entry={entry_ref}" + (f"&para={para}" if para else "")
        quote = str(annotation.get("excerpt") or "").strip()
        if not quote:
            quote = str(annotation.get("note") or "").strip()
        rendered_annotations.append({"quote": quote, "link": link})
    return {
        "title": str(getattr(detail, "title", "") or ""),
        "url": str(getattr(detail, "url", None) or ""),
        "source": str(getattr(detail, "feedTitle", "") or ""),
        "date": date,
        "published": published,
        "content": str(getattr(detail, "contentText", "") or ""),
        "annotations": rendered_annotations,
    }


def note_filename(title: str) -> str:
    """Obsidian note name from the article title (sanitized, no .md suffix
    needed by the URI scheme — but harmless and clearer in file mode)."""
    stem = _SAFE_FILENAME_RE.sub("-", str(title or "").strip()).strip("- .")
    stem = re.sub(r"\s+", " ", stem)[:_MAX_FILENAME_STEM].strip("- .")
    return f"{stem or '文章'}.md"


def render_export_markdown(
    template: str | None, context: dict[str, Any]
) -> TemplateRenderResult:
    return render_template(template if template and template.strip() else DEFAULT_TEMPLATE, context)


def prepare_handoff(
    *,
    profile: dict[str, Any],
    detail: Any,
    annotations: list[dict[str, Any]],
    template: str | None = None,
) -> HandoffPrepared:
    """Compose + render + decide URI vs file fallback (pure, testable)."""
    context = build_export_context(detail, annotations)
    rendered = render_export_markdown(template, context)
    filename = note_filename(str(getattr(detail, "title", "") or ""))
    uri = build_obsidian_new_uri(profile, file_name=filename, content=rendered.text)
    if "uri" in uri:
        return HandoffPrepared(
            mode="uri",
            uri=str(uri["uri"]),
            filename=filename,
            content=rendered.text,
            unknown_vars=rendered.unknown_vars,
            device_label=str(profile.get("label") or ""),
            reason=None,
        )
    return HandoffPrepared(
        mode="file",
        uri=None,
        filename=filename,
        content=rendered.text,
        unknown_vars=rendered.unknown_vars,
        device_label=str(profile.get("label") or ""),
        reason="tooLong" if uri.get("tooLong") else "uri_unavailable",
    )


async def prepare_handoff_for_entry(
    db,  # noqa: ANN001 — Database (RoutingDatabase, context-user routed)
    detail: Any,
    *,
    profile: dict[str, Any],
    entry_ref: str,
    template: str | None = None,
) -> HandoffPrepared:
    """Handoff with annotations collected from the per-user store."""
    annotations = await AnnotationStore(db).list_for_entry(entry_ref)
    return prepare_handoff(
        profile=profile, detail=detail, annotations=annotations, template=template
    )
