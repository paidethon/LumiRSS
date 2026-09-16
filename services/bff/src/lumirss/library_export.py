"""Deterministic Markdown export for Lumi library items (pool #22).

Contract:
- Same input → byte-identical output (no local clock, no locale, fixed
  field order, tags sorted by name);
- YAML frontmatter strings are always double-quoted with backslash and
  quote escaping — titles containing YAML specials cannot break the
  document;
- Filename is sanitized (CJK kept, path/control characters dropped,
  bounded) and never trusted from the raw title;
- Export is a pure HTTP download: it never writes the Obsidian vault or
  any other external store.
"""

import re

from lumirss.library import BookmarkView, LibraryStore
from lumirss.tags import TagStore

_SAFE_FILENAME_RE = re.compile(r"[^\w\u4e00-\u9fff-]+", re.UNICODE)
_MAX_FILENAME = 60


def yaml_quote(value: str) -> str:
    """Always-quoted YAML scalar; deterministic escaping."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return f'"{escaped}"'


def safe_filename(title: str, item_uuid: str) -> str:
    stem = _SAFE_FILENAME_RE.sub("-", title.strip()).strip("-")
    if not stem:
        stem = "lumi-export"
    stem = stem[:_MAX_FILENAME].rstrip("-")
    suffix = item_uuid.replace("-", "")[:8]
    return f"{stem}-{suffix}.md"


def compose_markdown(
    view: BookmarkView,
    tags: list[str],
) -> str:
    """Deterministic Markdown document for one bookmark."""
    lines = [
        "---",
        f"title: {yaml_quote(view.title)}",
        f"source: {yaml_quote(view.url or '')}",
        f"savedAt: {yaml_quote(view.created_at)}",
        f"kind: {yaml_quote(view.item_type)}",
        "tags: [" + ", ".join(yaml_quote(t) for t in sorted(tags)) + "]",
        "---",
        "",
        f"# {view.title}",
        "",
    ]
    if view.note:
        lines.append(view.note)
        lines.append("")
    if view.url:
        lines.append(f"[原文]({view.url})")
        lines.append("")
    return "\n".join(lines)


async def export_bookmark_markdown(
    library: LibraryStore,
    tags: TagStore,
    item_uuid: str,
) -> tuple[str, str] | None:
    """(filename, markdown) for one bookmark; None when absent."""
    view = await library.get_bookmark(item_uuid)
    if view is None:
        return None
    tag_rows = await tags.tags_for_item(view.ref)
    tag_names = [
        str(row["name"])
        for row in tag_rows
        if str(row.get("status", "active")) == "active"
    ]
    return safe_filename(view.title, item_uuid), compose_markdown(view, tag_names)
