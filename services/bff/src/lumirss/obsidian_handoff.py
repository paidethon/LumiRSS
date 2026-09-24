"""P16 导出到 Obsidian 交接（handoff）— 组装 + 渲染 + URI 预算裁决。

流程（一个入口 :func:`prepare_handoff`）：

1. 由 entryRef 解析文章（BFF adapter，读路径与 entries 路由同源）；
2. 收集该文章的批注（AnnotationStore 读 API，每用户库）——每条批注
   生成服务端等价的 buildParaLink 定位链接（``/reader?entry=<ref>&
   para=<anchorId>``，无凭据）；N134：再内嵌 Obsidian 块 id
   ``^lumi-<paraId>`` 与（配置了 LUMIRSS_PUBLIC_URL 时的）绝对反链；
3. 按用户模板渲染 Markdown（obsidian_template，纯替换）；
4. 构造官方 ``obsidian://new`` URI（obsidian_uri，8000 字符预算）。

裁决结果（诚实交接语义）：

- ``mode='uri'``  → 前端 ``window.location = uri`` 打开用户的 Obsidian，
  UI 文案必须是「已打开 Obsidian（请在 Obsidian 确认保存）」——绝不
  说「已写入」：Lumi 没写 Vault（ADR 0004），写入只发生在用户于
  Obsidian 中确认保存时；
- ``mode='file'`` → 内容超出 URI 预算（或 vault 未配置成 URI）→ 退回
  「下载 .md + 剪贴板」双通道，UI 说明实际走了哪条路。

N135 命名策略：``obsidian://new`` URI 无法探测目标库内是否已存在同名
笔记（官方 URI 限制，UI 文案必须如实说明），因此提供显式策略——
``timestamp_suffix``（默认，文件名追加 -YYYYMMDD-HHmm）或 ``exact``。
文件下载路径（library_export.safe_filename）本来就带 uuid 后缀、从不
覆盖，保持不变。

N139 导出侧校验：:func:`validate_export_markdown` 在交接前对组装好的
Markdown 做只读检查（断链 wikilink / 缺失附件 / 重复块 id），只报告、
绝不改写用户的 Vault 文件。
"""

import re
from dataclasses import dataclass, field
from typing import Any

from lumirss.annotation_store import AnnotationStore
from lumirss.obsidian_backlinks import parse_wikilink
from lumirss.obsidian_template import (
    DEFAULT_TEMPLATE,
    TemplateRenderResult,
    render_template,
)
from lumirss.obsidian_uri import build_obsidian_new_uri

_MAX_FILENAME_STEM = 80

_SAFE_FILENAME_RE = re.compile(r"[/\\:*?\"<>|]")

# N134 块 id（导出侧写入 + 投影侧扫描共用同一形状）。
BLOCK_ID_RE = re.compile(r"\^lumi-([A-Za-z0-9_-]+)")

# Markdown 图片/相对链接：![alt](src)
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")

# N135 命名策略（单一事实源；迁移默认值与其保持一致）。
EXPORT_NAME_POLICIES: tuple[str, ...] = ("timestamp_suffix", "exact")
DEFAULT_NAME_POLICY = "timestamp_suffix"

# N139 校验报告里每类问题的固定 kind。
ISSUE_BROKEN_WIKILINK = "broken_wikilink"
ISSUE_MISSING_ATTACHMENT = "missing_attachment"
ISSUE_DUPLICATE_BLOCK_ID = "duplicate_block_id"

# N139 每类问题最多报告条数（有界，不淹没 UI）。
_MAX_ISSUES_PER_KIND = 50

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
    # N137：本次交接实际包含的批注 id（成功组合后由路由层 mark 导出）。
    annotation_ids: list[str] = field(default_factory=list)


def _entry_date(detail: Any) -> tuple[str, str]:
    """(展示日期, 原始 published)；发布时间缺失回退收录时间（诚实）。"""
    published = getattr(detail, "publishedAt", None) or ""
    if published:
        return published[:10], published
    crawled = getattr(detail, "crawledAt", None) or ""
    return (crawled[:10] if crawled else ""), published


def build_export_context(
    detail: Any,
    annotations: list[dict[str, Any]],
    *,
    public_url: str = "",
) -> dict[str, Any]:
    """Template context from one EntryDetail + its annotations.

    ``public_url``（LUMIRSS_PUBLIC_URL，尾斜杠已剥）非空且批注有段落
    锚点时，每条批注额外携带绝对反链（→ LumiRSS 原文）与 Obsidian 块
    id（^lumi-<paraId>）；否则诚实省略对应字段，绝不生成打不开的链接。
    """
    date, published = _entry_date(detail)
    base = public_url.strip().rstrip("/")
    rendered_annotations = []
    for annotation in annotations:
        anchor = annotation.get("anchor")
        para = ""
        if isinstance(anchor, dict):
            para = str(anchor.get("paraId") or "")
        entry_ref = str(annotation.get("entry_ref") or getattr(detail, "entryRef", ""))
        query = f"entry={entry_ref}" + (f"&para={para}" if para else "")
        link = f"/reader?{query}"
        backlink = f"{base}/reader?{query}" if (base and para) else ""
        block_id = f"lumi-{para}" if para else ""
        quote = str(annotation.get("excerpt") or "").strip()
        if not quote:
            quote = str(annotation.get("note") or "").strip()
        rendered_annotations.append(
            {
                "quote": quote,
                "link": link,
                "backlink": backlink,
                "blockId": block_id,
            }
        )
    return {
        "title": str(getattr(detail, "title", "") or ""),
        "url": str(getattr(detail, "url", None) or ""),
        "source": str(getattr(detail, "feedTitle", "") or ""),
        "date": date,
        "published": published,
        "content": str(getattr(detail, "contentText", "") or ""),
        "annotations": rendered_annotations,
    }


def note_filename(
    title: str,
    *,
    policy: str = DEFAULT_NAME_POLICY,
    now: str | None = None,
) -> str:
    """Obsidian note name from the article title (sanitized, no .md suffix
    needed by the URI scheme — but harmless and clearer in file mode).

    N135：``timestamp_suffix``（默认）在文件名追加 ``-YYYYMMDD-HHmm``，
    避免重复导出覆盖既有笔记；``exact`` 保持纯标题。文件下载路径
    （library_export.safe_filename 的 uuid 后缀）不受此影响、从不覆盖。
    """
    stem = _SAFE_FILENAME_RE.sub("-", str(title or "").strip()).strip("- .")
    stem = re.sub(r"\s+", " ", stem)[:_MAX_FILENAME_STEM].strip("- .")
    stem = stem or "文章"
    if policy == "timestamp_suffix":
        stamp = _timestamp_suffix(now)
        return f"{stem}-{stamp}.md"
    return f"{stem}.md"


def _timestamp_suffix(now: str | None) -> str:
    """utc_now() 形状的时间戳 → ``YYYYMMDD-HHmm``（可注入以便测试）。"""
    raw = (now or "").strip()
    if not raw:
        from lumirss.util import utc_now

        raw = utc_now()
    # 2026-09-23T08:00 → 20260923-0800
    return raw[:16].replace("-", "").replace("T", "-").replace(":", "")


def validate_name_policy(policy: str | None) -> str:
    """非法策略 → 回退默认（存档层已校验；此处兜底，绝不抛错中断交接）。"""
    return policy if policy in EXPORT_NAME_POLICIES else DEFAULT_NAME_POLICY


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
    public_url: str = "",
    name_policy: str = DEFAULT_NAME_POLICY,
    now: str | None = None,
) -> HandoffPrepared:
    """Compose + render + decide URI vs file fallback (pure, testable)."""
    context = build_export_context(detail, annotations, public_url=public_url)
    rendered = render_export_markdown(template, context)
    filename = note_filename(
        str(getattr(detail, "title", "") or ""),
        policy=validate_name_policy(name_policy),
        now=now,
    )
    uri = build_obsidian_new_uri(profile, file_name=filename, content=rendered.text)
    annotation_ids = [
        str(a.get("id")) for a in annotations if a.get("id")
    ]
    if "uri" in uri:
        return HandoffPrepared(
            mode="uri",
            uri=str(uri["uri"]),
            filename=filename,
            content=rendered.text,
            unknown_vars=rendered.unknown_vars,
            device_label=str(profile.get("label") or ""),
            reason=None,
            annotation_ids=annotation_ids,
        )
    return HandoffPrepared(
        mode="file",
        uri=None,
        filename=filename,
        content=rendered.text,
        unknown_vars=rendered.unknown_vars,
        device_label=str(profile.get("label") or ""),
        reason="tooLong" if uri.get("tooLong") else "uri_unavailable",
        annotation_ids=annotation_ids,
    )


async def prepare_handoff_for_entry(
    db,  # noqa: ANN001 — Database (RoutingDatabase, context-user routed)
    detail: Any,
    *,
    profile: dict[str, Any],
    entry_ref: str,
    template: str | None = None,
    public_url: str = "",
    name_policy: str = DEFAULT_NAME_POLICY,
    only_updated_after: str | None = None,
    now: str | None = None,
) -> HandoffPrepared:
    """Handoff with annotations collected from the per-user store.

    ``only_updated_after``（N137 增量导出）：只携带 updated_at 晚于水位
    的批注（None = 全量，行为与历史版本一致）。
    """
    annotations = await AnnotationStore(db).list_for_entry(
        entry_ref, updated_after=only_updated_after
    )
    return prepare_handoff(
        profile=profile,
        detail=detail,
        annotations=annotations,
        template=template,
        public_url=public_url,
        name_policy=name_policy,
        now=now,
    )


# ---------------------------------------------------------------------------
# N139 导出侧链接校验（只读报告；绝不改写 Vault 文件）
# ---------------------------------------------------------------------------


def _normalize_key(rel_path: str) -> str:
    return rel_path.strip().lower().removesuffix(".md")


def build_projection_index(notes: list[dict[str, Any]]) -> dict[str, str]:
    """obsidian_notes 行 → 解析键集合（rel_path / stem / title）。

    与反链解析（obsidian_backlinks）同一套键规则，保证「校验说没问题的
    wikilink，投影扫描也解析得出来」。"""
    index: dict[str, str] = {}
    for note in notes:
        rel_path = str(note.get("relPath") or note.get("rel_path") or "")
        title = str(note.get("title") or "").strip()
        if rel_path:
            key = _normalize_key(rel_path)
            if key:
                index[key] = rel_path
            stem = key.rsplit("/", 1)[-1]
            if stem:
                index.setdefault(stem, rel_path)
        if title:
            index.setdefault(title, rel_path)
    return index


def validate_export_markdown(
    markdown: str,
    *,
    projection_index: dict[str, str],
    vault_exists: Any = None,
) -> list[dict[str, str]]:
    """只读校验组装好的交接 Markdown，返回 ``[{kind, detail, suggestion}]``。

    - ``broken_wikilink``：``[[target]]`` 在投影索引（rel_path/stem/标题）
      中解析不出；
    - ``missing_attachment``：相对路径图片在投影索引与 Vault（提供
      ``vault_exists`` 回调时）中都不存在；无法访问 Vault 时跳过该项
      检查（诚实局限，绝不凭空报假阳性）；
    - ``duplicate_block_id``：同一 ``^lumi-`` 块 id 在本次导出内出现多次
      （Obsidian 块 id 冲突会让回跳定位到错误块）。

    只报告，绝不改写任何文件。
    """
    issues: list[dict[str, str]] = []

    def _add(kind: str, detail: str, suggestion: str) -> None:
        if sum(1 for i in issues if i["kind"] == kind) >= _MAX_ISSUES_PER_KIND:
            return
        issues.append({"kind": kind, "detail": detail, "suggestion": suggestion})

    # 1) wikilinks（复用反链解析；穿越/解析失败都如实列出）
    seen_links: set[str] = set()
    for chunk in str(markdown or "").split("[[")[1:]:
        raw = chunk.split("]]", 1)[0].strip()
        if not raw or raw in seen_links:
            continue
        seen_links.add(raw)
        parsed = parse_wikilink(raw)
        if parsed.escaped_vault:
            _add(
                ISSUE_BROKEN_WIKILINK,
                f"[[{raw}]]：路径越出 Vault（.. 或绝对路径）。",
                "改为 Vault 内的相对路径或笔记名。",
            )
            continue
        if not parsed.target:
            continue
        if _normalize_key(parsed.target) not in projection_index and parsed.target not in projection_index:
            _add(
                ISSUE_BROKEN_WIKILINK,
                f"[[{raw}]]：投影索引中没有匹配的笔记。",
                "确认目标笔记已同步（去 Obsidian 库重扫），或修正链接名。",
            )

    # 2) 相对路径图片 → 附件存在性（vault 回调可用时才检查）
    for src in _MD_IMAGE_RE.findall(str(markdown or "")):
        candidate = src.strip()
        if not candidate or "://" in candidate or candidate.startswith("data:"):
            continue
        if _normalize_key(candidate) in projection_index or candidate in projection_index:
            continue
        if vault_exists is None:
            continue  # 无法核对 Vault：诚实跳过，不报假阳性
        verdict = vault_exists(candidate)
        if verdict is False:
            _add(
                ISSUE_MISSING_ATTACHMENT,
                f"图片 {candidate} 在 Vault 中不存在。",
                "确认附件路径，或先把文件放进 Vault 再导出。",
            )

    # 3) 重复块 id（同一导出内 ^lumi- 冲突）
    counts: dict[str, int] = {}
    for match in BLOCK_ID_RE.finditer(str(markdown or "")):
        block_id = f"lumi-{match.group(1)}"
        counts[block_id] = counts.get(block_id, 0) + 1
    for block_id, count in counts.items():
        if count > 1:
            _add(
                ISSUE_DUPLICATE_BLOCK_ID,
                f"块 id ^{block_id} 在本次导出中出现 {count} 次。",
                "同一段落的批注共用锚点是正常的；不同内容出现同 id 说明锚点异常，请重新标注后再导出。",
            )
    return issues
