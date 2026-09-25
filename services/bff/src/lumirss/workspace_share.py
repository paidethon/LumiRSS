"""N116 汇编只读分享包 —— 自包含静态 HTML（无脚本、无凭据、无本地路径）。

- 输入 = N114 汇编草稿（同一大纲与解析口径）+ 逐条解析视图（来源标注）；
- 自包含：单文件、内联 CSS、零 JavaScript、零外链资源；
- 引文链接策略（诚实省略优于打不开的链接）：
  * 绝对 http(s) 引文（library 外链）→ 恒为真链接（本身就是公开 URL）；
  * 应用内路由引文（/reader?entry=… 等）→ 仅当配置了
    ``LUMIRSS_PUBLIC_URL`` 时拼成绝对公开链接；否则渲染为纯文本
    （无 href 的锚语义 = 占位 span），绝不产出打不开的相对路径；
- 隐私硬约束（测试断言）：包内绝无 cookie / token / 凭据 / 绝对本地
  路径 / 内部 opaque ref 明细；私人笔记（includeNotes 固定 false）
  与 RAG 评测样例绝不进入分享包；
- 每条附「来源标注」（来源标题 / 发布时间 / 引文），文末固定隐私提示：
  导出内容包含私人摘录，请自行判断分享范围。
"""

import html
from datetime import datetime
from typing import Any

_PRICACY_NOTE = "导出内容包含私人摘录，请自行判断分享范围。"

_CSS = """
body { font-family: -apple-system, 'Segoe UI', 'Noto Sans SC', sans-serif;
       max-width: 760px; margin: 2rem auto; padding: 0 1rem; color: #1f2430; }
h1 { font-size: 1.5rem; } h2 { border-bottom: 1px solid #d8dde6;
       padding-bottom: .3rem; margin-top: 2rem; }
.meta { color: #5b6472; font-size: .9rem; }
article { margin: 1.2rem 0; padding: .8rem 1rem; border: 1px solid #e3e7ee;
       border-radius: 8px; }
article h3 { margin: 0 0 .4rem; font-size: 1.05rem; }
.excerpt { white-space: pre-wrap; }
.provenance { font-size: .82rem; color: #5b6472; margin-top: .5rem; }
.provenance a { color: #2563eb; word-break: break-all; }
.cite-plain { word-break: break-all; }
.privacy-note { margin-top: 2.5rem; padding: .8rem 1rem; background: #fdf6e3;
       border: 1px solid #e8d9a0; border-radius: 8px; font-size: .88rem; }
.muted { color: #8a93a3; }
"""


def _escape(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _citation_href(citation: str, public_base_url: str) -> str | None:
    """分享包里的引文 href（None = 无链接，纯文本诚实省略）。

    绝对 http(s) 引文本身就是公开 URL；应用内路由需要公开基底。
    非公开基底时返回 None——绝不输出相对路径链接。"""
    if citation.startswith("http://") or citation.startswith("https://"):
        return citation
    if public_base_url and citation.startswith("/"):
        return public_base_url.rstrip("/") + citation
    return None


def _format_published(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    return parsed.strftime("%Y-%m-%d")


def render_share_package_html(
    draft: Any,
    resolved: dict[str, Any],
    *,
    public_base_url: str,
) -> str:
    """CompileResponse + 解析视图 → 自包含 HTML 字符串。

    ``resolved`` 是 {itemRef: ResolvedItem}——来源标注取 ``source`` /
    ``datetime`` / ``url``，绝不包含内部存储细节。"""
    parts: list[str] = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="zh-CN">')
    parts.append("<head>")
    parts.append('<meta charset="utf-8">')
    parts.append(
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
    )
    parts.append(f"<title>{_escape(draft.workspaceName)} — 分享汇编</title>")
    parts.append(f"<style>{_CSS}</style>")
    parts.append("</head>")
    parts.append("<body>")
    parts.append(f"<h1>{_escape(draft.workspaceName)}（只读分享汇编）</h1>")
    parts.append(
        f'<p class="meta">生成时间：{_escape(draft.generatedAt)} · '
        f"收录 {draft.includedCount} 条 / 排除 {draft.excludedMissing} 条</p>"
    )
    for section in draft.sections:
        parts.append(f"<h2>{_escape(section.title)}</h2>")
        if not section.items:
            parts.append('<p class="muted">（本节暂无条目）</p>')
            continue
        for item in section.items:
            view = resolved.get(item.itemRef)
            source = getattr(view, "source", None) if view is not None else None
            published = (
                getattr(view, "datetime", None) if view is not None else None
            )
            provenance_bits = ["来源标注"]
            if source:
                provenance_bits.append(str(source))
            formatted = _format_published(published)
            if formatted:
                provenance_bits.append(formatted)
            parts.append("<article>")
            parts.append(f"<h3>{_escape(item.title)}</h3>")
            if item.excerpt:
                parts.append(
                    f'<p class="excerpt">{_escape(item.excerpt)}</p>'
                )
            href = _citation_href(item.citation, public_base_url)
            if href is not None:
                citation_html = (
                    f'<a href="{_escape(href)}" rel="noopener noreferrer nofollow">'
                    f"{_escape(item.citation)}</a>"
                )
            else:
                citation_html = (
                    f'<span class="cite-plain">{_escape(item.citation)}</span>'
                )
            parts.append(
                f'<p class="provenance">{_escape(" · ".join(provenance_bits))}'
                f" · 引文：{citation_html}</p>"
            )
            parts.append("</article>")
    if draft.excluded:
        parts.append("<h2>未收录（诚实排除）</h2>")
        parts.append("<ul>")
        for item in draft.excluded:
            parts.append(
                f"<li>{_escape(item.reason)}</li>"
            )
        parts.append("</ul>")
    parts.append(
        f'<p class="privacy-note">{_escape(_PRICACY_NOTE)}</p>'
    )
    parts.append("</body>")
    parts.append("</html>")
    return "\n".join(parts)
