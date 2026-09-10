#!/usr/bin/env python3
"""PoC 05-bookmarks: Netscape bookmark HTML import/export roundtrip.

Parses a real browser-format Netscape file (with folders, tags in the
NETSCAPE-Bookmark-file-1 DTD convention), normalizes into LibraryItem
drafts, and exports back — proving lossless roundtrip for v1 scope.
Run: uv run python poc_bookmarks.py
"""
from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

# A minimal but structurally faithful Netscape bookmark file (same shape the
# Chrome/Firefox exporters emit: DL/DT nesting, ADD_DATE unix ints, TAGS attr).
NETSCAPE_HTML = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
  <DT><H3 ADD_DATE="1700000000" LAST_MODIFIED="1700000100">AI Reading</H3>
  <DL><p>
    <DT><A HREF="https://simonwillison.net/2026/Aug/12/sandboxed-python/" ADD_DATE="1700000200" TAGS="llm,sandbox">Sandboxed Python</A>
    <DT><A HREF="https://blog.vllm.ai/2026/01/05/vllm-v1.html" ADD_DATE="1700000300">vLLM V1</A>
    <DT><H3 ADD_DATE="1700000400">Deep Dives</H3>
    <DL><p>
      <DT><A HREF="https://lilianweng.github.io/posts/2026-diffusion/" ADD_DATE="1700000500" TAGS="diffusion">Diffusion Notes</A>
    </DL><p>
  </DL><p>
  <DT><A HREF="https://news.ycombinator.com/" ADD_DATE="1700000600">HN</A>
</DL><p>
"""

A_RE = re.compile(r'<A\s+HREF="([^"]+)"([^>]*)>(.*?)</A>', re.IGNORECASE | re.DOTALL)
H3_RE = re.compile(r'<H3([^>]*)>(.*?)</H3>', re.IGNORECASE)
ATTR_RE = re.compile(r'(\w+)="([^"]*)"')


def parse(netscape: str) -> list[dict]:
    """Folder-aware parse: items carry a `folders` path list."""
    items: list[dict] = []
    stack: list[str] = []
    for line in netscape.splitlines():
        h3 = H3_RE.search(line)
        if h3:
            attrs = dict(ATTR_RE.findall(h3.group(1)))
            stack.append(html.unescape(h3.group(2).strip()))
            _ = attrs  # folder ADD_DATE ignored in v1
            continue
        if "</dl>" in line.lower() and stack:
            stack.pop()
        a = A_RE.search(line)
        if a:
            href, attr_str, text = a.group(1), a.group(2), a.group(3)
            attrs = dict(ATTR_RE.findall(attr_str))
            items.append({
                "url": html.unescape(href),
                "title": html.unescape(re.sub(r"<[^>]+>", "", text)).strip(),
                "folders": list(stack),
                "tags": [t for t in attrs.get("TAGS", "").split(",") if t],
                "added_at": attrs.get("ADD_DATE"),
            })
    return items


def export(items: list[dict]) -> str:
    """Render back to Netscape HTML with folder nesting."""
    out = ['<!DOCTYPE NETSCAPE-Bookmark-file-1>', '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
           "<TITLE>Bookmarks</TITLE>", "<H1>Bookmarks</H1>", "<DL><p>"]
    # group by top folder path to rebuild nesting (deterministic order)
    folders: dict[str, list[dict]] = {}
    loose: list[dict] = []
    for it in items:
        if it["folders"]:
            folders.setdefault("/".join(it["folders"]), []).append(it)
        else:
            loose.append(it)
    for path, group in sorted(folders.items()):
        depth = len(path.split("/"))
        for i, part in enumerate(path.split("/")):
            out.append("  " * (i + 1) + f'<DT><H3 ADD_DATE="1700000000">{html.escape(part)}</H3>')
            out.append("  " * (i + 1) + "<DL><p>")
        for it in group:
            tags = f' TAGS="{html.escape(",".join(it["tags"]))}"' if it["tags"] else ""
            out.append("  " * (depth + 1) + f'<DT><A HREF="{html.escape(it["url"])}" ADD_DATE="{it["added_at"] or "0"}"{tags}>{html.escape(it["title"])}</A>')
        for _ in path.split("/"):
            out.append("  " * depth + "</DL><p>")
    for it in loose:
        out.append(f'  <DT><A HREF="{html.escape(it["url"])}" ADD_DATE="{it["added_at"] or "0"}">{html.escape(it["title"])}</A>')
    out.append("</DL><p>")
    return "\n".join(out)


def main() -> None:
    t0 = time.perf_counter()
    items = parse(NETSCAPE_HTML)
    print(f"parsed {len(items)} bookmarks")
    for it in items:
        print(f"  {'/'.join(it['folders']) or '(root)':16s} {it['title'][:40]:42s} tags={it['tags']}")
    exported = export(items)
    reparsed = parse(exported)
    fields = lambda lst: [{k: it[k] for k in ("url", "title", "folders", "tags")} for it in lst]
    lossless = fields(items) == fields(reparsed)
    print(f"roundtrip lossless: {lossless}")
    (HERE / "bookmarks-export-roundtrip.html").write_text(exported, encoding="utf-8")
    print(f"OK in {time.perf_counter()-t0:.3f}s")


if __name__ == "__main__":
    main()
