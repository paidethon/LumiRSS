"""Netscape bookmarks.html import/export (phase2 M1).

The Netscape bookmark format is the stable de-facto interchange standard
of every browser exporter. The parser below is deliberately small and
line-oriented (proven by the phase2 PoC roundtrip): it accepts folder
nesting (``<DT><H3>`` + ``<DL>``), ``TAGS`` attributes and ``ADD_DATE``,
and treats the whole input as untrusted — size and item-count caps are
enforced by the caller; malformed lines are skipped, not fatal.

Export renders the same shape back; folders become nested lists so an
import→export→reimport cycle is lossless for the v1 field set
(url, title, folders, tags, added_at).
"""

import html
import re
from dataclasses import dataclass, field

_A_RE = re.compile(r'<A\s+HREF="([^"]*)"([^>]*)>(.*?)</A>', re.IGNORECASE | re.DOTALL)
_H3_RE = re.compile(r"<H3([^>]*)>(.*?)</H3>", re.IGNORECASE)
_ATTR_RE = re.compile(r'([A-Za-z_:][\w:.-]*)="([^"]*)"')
_TAG_RE = re.compile(r"<[^>]+>")
_ADD_DATE_RE = re.compile(r"^\d{1,13}$")


class NetscapeParseError(ValueError):
    """The input is not recognizable Netscape bookmark HTML at all."""


@dataclass
class NetscapeBookmark:
    url: str
    title: str
    folders: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    added_at: str | None = None


def parse_netscape(text: str) -> list[NetscapeBookmark]:
    """Folder-aware parse; items carry a ``folders`` path list."""
    if "<a " not in text.lower() and "<dt>" not in text.lower():
        raise NetscapeParseError("No bookmark anchors found in input.")
    items: list[NetscapeBookmark] = []
    stack: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith("<h3") or "<h3" in lowered:
            match = _H3_RE.search(stripped)
            if match is not None:
                title = html.unescape(_TAG_RE.sub("", match.group(2))).strip()
                stack.append(title)
            continue
        if "</dl>" in lowered and stack:
            stack.pop()
            # A line can close a folder and still carry anchors.
        for anchor in _A_RE.finditer(stripped):
            href = html.unescape(anchor.group(1)).strip()
            if not href:
                continue
            attrs = {
                name.upper(): value
                for name, value in _ATTR_RE.findall(anchor.group(2))
            }
            title = html.unescape(_TAG_RE.sub("", anchor.group(3))).strip()
            tags = [t for t in html.unescape(attrs.get("TAGS", "")).split(",") if t]
            added = attrs.get("ADD_DATE")
            if added is not None and not _ADD_DATE_RE.match(added):
                added = None
            items.append(
                NetscapeBookmark(
                    url=href,
                    title=title or href,
                    folders=list(stack),
                    tags=tags,
                    added_at=added,
                )
            )
    return items


def export_netscape(items: list[NetscapeBookmark]) -> str:
    """Render bookmarks back to Netscape HTML with folder nesting.

    Items are placed into a folder tree keyed by their full path so the
    render is independent of input order and duplicate folder names.
    """
    roots: dict[str, dict] = {}

    def _children(node: dict) -> dict:
        return node.setdefault("__children", {})

    def _bucket(node: dict, path: tuple[str, ...]) -> list[NetscapeBookmark]:
        current = node
        for name in path:
            children = _children(current)
            current = children.setdefault(name, {})
        return current.setdefault("__items", [])

    for item in items:
        _bucket(roots, tuple(item.folders)).append(item)

    lines = [
        "<!DOCTYPE NETSCAPE-Bookmark-file-1>",
        '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
        "<TITLE>Bookmarks</TITLE>",
        "<H1>Bookmarks</H1>",
        "<DL><p>",
    ]

    def _render_anchor(item: NetscapeBookmark, indent: str) -> None:
        attrs = f' ADD_DATE="{item.added_at}"' if item.added_at else ""
        if item.tags:
            attrs += f' TAGS="{html.escape(",".join(item.tags), quote=True)}"'
        lines.append(
            f'{indent}<DT><A HREF="{html.escape(item.url, quote=True)}"'
            f"{attrs}>{html.escape(item.title)}</A>"
        )

    def _render_folder(name: str, node: dict, depth: int) -> None:
        indent = "  " * depth
        lines.append(f"{indent}<DT><H3>{html.escape(name)}</H3>")
        lines.append(f"{indent}<DL><p>")
        for item in node.get("__items", []):
            _render_anchor(item, indent + "  ")
        for child_name in sorted(node.get("__children", {})):
            _render_folder(child_name, node["__children"][child_name], depth + 1)
        lines.append(f"{indent}</DL><p>")

    for item in roots.get("__items", []):
        _render_anchor(item, "  ")
    for name in sorted(roots.get("__children", {})):
        _render_folder(name, roots["__children"][name], 1)
    lines.append("</DL><p>")
    return "\n".join(lines) + "\n"
