"""Netscape bookmarks.html import/export tests (phase2 M1).

Roundtrip fidelity (Chinese titles, nested folders, tags), idempotent
re-import, per-item error reporting and the hostile-input guards.
"""

import re

import pytest

from lumirss.bookmarks_io import (
    NetscapeBookmark,
    NetscapeParseError,
    export_netscape,
    parse_netscape,
)

SAMPLE = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
  <DT><H3 ADD_DATE="1700000000">AI Reading</H3>
  <DL><p>
    <DT><A HREF="https://simonwillison.net/sandboxed-python/" ADD_DATE="1700000200" TAGS="llm,sandbox">Sandboxed Python</A>
    <DT><A HREF="https://blog.vllm.ai/vllm-v1.html" ADD_DATE="1700000300">vLLM V1</A>
    <DT><H3>深度文章</H3>
    <DL><p>
      <DT><A HREF="https://lilianweng.github.io/diffusion/" TAGS="diffusion">扩散模型笔记</A>
    </DL><p>
  </DL><p>
  <DT><A HREF="https://news.ycombinator.com/">HN</A>
</DL><p>
"""


def test_parse_extracts_folders_tags_chinese():
    items = parse_netscape(SAMPLE)
    assert len(items) == 4
    deep = next(i for i in items if "扩散" in i.title)
    assert deep.folders == ["AI Reading", "深度文章"]
    assert deep.tags == ["diffusion"]
    loose = next(i for i in items if i.title == "HN")
    assert loose.folders == []


def test_import_export_reimport_lossless():
    items = parse_netscape(SAMPLE)
    once = export_netscape(items)
    twice = export_netscape(parse_netscape(once))
    assert once == twice
    # Field-level fidelity across the cycle.
    final = parse_netscape(twice)
    assert sorted((i.url, i.title, tuple(i.folders), tuple(i.tags)) for i in final) == sorted(
        (i.url, i.title, tuple(i.folders), tuple(i.tags)) for i in items
    )


def test_parse_rejects_input_without_anchors():
    with pytest.raises(NetscapeParseError):
        parse_netscape("<html><body>hello</body></html>")


def test_export_escapes_hostile_titles():
    items = [
        NetscapeBookmark(
            url='https://evil.example/"onclick="javascript:x',
            title="<script>alert(1)</script>",
            tags=['"><b>'],
        )
    ]
    rendered = export_netscape(items)
    # Attribute delimiters are escaped, so the href cannot be broken out of
    # and no raw markup survives in the title/tags positions.
    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert re.search(r'HREF="[^"]*"[^>]*onclick="javascript', rendered) is None
    assert rendered.count('HREF="') == 1  # exactly one well-formed anchor


def test_import_api_reports_per_item_failures(client):
    payload = (
        "<!DOCTYPE NETSCAPE-Bookmark-file-1><DL><p>"
        '<DT><A HREF="https://good.example/">好的</A>'
        '<DT><A HREF="javascript:alert(1)">坏</A>'
        '<DT><A HREF="https://dup.example/">首现</A>'
        "</DL><p>"
    ).encode()
    first = client.post("/api/v1/library/bookmarks/import", content=payload)
    assert first.status_code == 200
    body = first.json()
    assert body["imported"] == 2
    assert len(body["failed"]) == 1
    assert body["failed"][0]["url"] == "javascript:alert(1)"

    # Re-import: everything already present → skipped, imported=0.
    again = client.post("/api/v1/library/bookmarks/import", content=payload)
    assert again.json()["imported"] == 0
    assert again.json()["skipped"] == 2


def test_import_api_rejects_garbage_and_oversize(client):
    response = client.post(
        "/api/v1/library/bookmarks/import", content=b"plain text no anchors"
    )
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "bookmarks_import_invalid"

    huge = b"<DT><A HREF=\"https://x.com/\">x</A>" * (10 * 1024 * 1024 // 34 + 2)
    response = client.post("/api/v1/library/bookmarks/import", content=huge)
    # Either the route cap (400) or the global body ceiling (413) rejects.
    assert response.status_code in (400, 413)


def test_export_api_roundtrips_through_import(client):
    client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://example.com/one", "title": "一"},
    )
    client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://example.com/two", "title": "二"},
    )
    exported = client.get("/api/v1/library/bookmarks/export.html")
    assert exported.status_code == 200
    assert "attachment" in exported.headers["content-disposition"]
    items = parse_netscape(exported.text)
    assert {i.url for i in items} == {
        "https://example.com/one",
        "https://example.com/two",
    }
