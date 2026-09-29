"""NEW-289 简报纯文本邮件文件 —— 确认期次导出为可检查的 EML 文件。

硬边界（与 mail_digest 的 SMTP 发送通道彻底分开）：
- 本模块只构建 RFC 5322 消息字节（email.message.EmailMessage，纯
  stdlib）：没有任何 SMTP 客户端导入、不连网、不需要任何 SMTP 凭据；
- 只导出「本人确认」的期次（草稿 → 409）；响应是 attachment 文件
  下载，发送与否、发到哪，完全由用户拿文件后自己决定；
- 正文如实携带编辑来源标记（287）与更正提示（290）。
"""

from datetime import datetime
from email.message import EmailMessage
from email.utils import format_datetime
from typing import Any

from lumirss.new281_briefings import BriefingStateConflict as IssueStateConflict
from lumirss.new281_briefings import provenance_label

_FILENAME_SAFE = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
)


def slugify(text: str, fallback: str = "briefing") -> str:
    slug = "".join(ch if ch in _FILENAME_SAFE else "-" for ch in text.strip())
    slug = slug.strip("-") or fallback
    return slug[:60]


def build_eml(
    issue: dict[str, Any],
    corrections: list[dict[str, Any]],
) -> bytes:
    """确认期次 → RFC 5322 字节（text/plain + text/html 双部分）。"""
    if issue.get("status") != "confirmed":
        raise IssueStateConflict("只有已确认的期次可导出 EML。")
    confirmed_at = str(issue.get("confirmedAt") or "")
    subject = str(issue["title"])
    if corrections:
        subject = f"{subject}（更正 {len(corrections)} 条）"

    lines: list[str] = [f"{issue['title']}", ""]
    range_bits = [bit for bit in (issue.get("rangeFrom"), issue.get("rangeTo")) if bit]
    if range_bits:
        lines.append(f"文章范围：{range_bits[0]} → {range_bits[-1]}")
        lines.append("")
    sections = issue.get("sections") or []
    items = issue.get("items") or []
    for section in sections:
        key = str(section.get("key"))
        label = str(section.get("label") or key)
        in_section = [i for i in items if i.get("sectionKey") == key]
        if not in_section:
            continue
        lines.append(f"== {label} ==")
        for item in in_section:
            marker = provenance_label(str(item.get("provenance") or "manual"))
            lines.append(f"* [{marker}] {item.get('title')}")
            feed_title = str(item.get("feedTitle") or "")
            if feed_title:
                lines.append(f"  来源：{feed_title}")
            published = str(item.get("publishedAt") or "")
            if published:
                lines.append(f"  发布：{published}")
            if item.get("pulledBack"):
                lines.append("  （迟到调回：编辑手动从下一期调回本期）")
            excerpt = str(item.get("excerpt") or "")
            if excerpt:
                lines.append(f"  {excerpt}")
            if item.get("url"):
                lines.append(f"  链接：{item['url']}")
        lines.append("")
    for correction in corrections:
        created = str(correction.get("createdAt") or "")
        lines.append(f"【更正 {created}】{correction.get('body')}")
    if corrections:
        lines.append("")
        lines.append("以上更正为追加记录，原期次内容未做静默替换。")
    text = "\n".join(lines).rstrip() + "\n"

    html_parts = [f"<h1>{_esc(str(issue['title']))}</h1>"]
    for section in sections:
        key = str(section.get("key"))
        label = str(section.get("label") or key)
        in_section = [i for i in items if i.get("sectionKey") == key]
        if not in_section:
            continue
        html_parts.append(f"<h2>{_esc(label)}</h2><ul>")
        for item in in_section:
            marker = provenance_label(str(item.get("provenance") or "manual"))
            title = _esc(str(item.get("title") or ""))
            url = str(item.get("url") or "")
            link = (
                f' <a href="{_esc(url)}">原文</a>' if _safe_href(url) else ""
            )
            html_parts.append(
                f"<li>【{_esc(marker)}】{title}{link}<br>"
                f"<small>{_esc(str(item.get('feedTitle') or ''))}</small></li>"
            )
        html_parts.append("</ul>")
    for correction in corrections:
        html_parts.append(
            f"<p><strong>更正 {_esc(str(correction.get('createdAt') or ''))}</strong>"
            f"：{_esc(str(correction.get('body') or ''))}</p>"
        )
    html = "".join(html_parts)

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = "LumiRSS Briefing <briefing@lumirss.local>"
    message["To"] = "undisclosed-recipients:;"
    if confirmed_at:
        try:
            parsed = datetime.fromisoformat(confirmed_at.replace("Z", "+00:00"))
            message["Date"] = format_datetime(parsed)
        except ValueError:
            pass
    message["Message-ID"] = f"<briefing-{issue['id']}@lumirss.local>"
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    return message.as_bytes()


def filename_for(issue: dict[str, Any]) -> str:
    return f"{slugify(str(issue.get('title') or ''))}-{issue['id'][:8]}.eml"


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _safe_href(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")
