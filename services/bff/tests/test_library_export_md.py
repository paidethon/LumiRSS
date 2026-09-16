"""Deterministic Markdown export（pool #22）：相同输入字节级一致、YAML
特殊字符安全、文件名清洗、下载不落盘到 Obsidian Vault。"""

import re

from lumirss.library_export import (
    compose_markdown,
    safe_filename,
    yaml_quote,
)


def run(coroutine):
    import asyncio

    return asyncio.run(coroutine)


def test_yaml_quote_escapes_breaking_characters():
    assert yaml_quote('含 "引号" 的标题') == '"含 \\"引号\\" 的标题"'
    assert yaml_quote("back\\slash") == '"back\\\\slash"'
    assert yaml_quote("line1\nline2\ttab") == '"line1\\nline2\\ttab"'
    # 输出永远被双引号包裹 → 不可能产生裸布尔/数字语义。
    assert yaml_quote("true").startswith('"')


def test_safe_filename_strips_paths_and_bounds_length():
    name = safe_filename('../../etc/passwd/../../скрыто', '0123456789abcdef')
    assert '/' not in name and '\\' not in name
    assert name.endswith('-01234567.md')
    assert len(name) <= 72
    # CJK 标题保留；全标点标题回退默认名。
    assert safe_filename('读书笔记', '0123456789abcdef').startswith('读书笔记-')
    assert safe_filename('!!!', '0123456789abcdef').startswith('lumi-export-')


def _view(title="标题", url="https://example.com/a", note="笔记内容", created_at="2026-09-17T01:00:00+00:00"):
    from lumirss.library import BookmarkView

    return BookmarkView(
        ref="library:0123456789abcdef",
        item_type="url",
        url=url,
        rss_item_ref=None,
        title=title,
        note=note,
        created_at=created_at,
    )


def test_compose_markdown_is_deterministic_and_escaped():
    v = _view('标题 "带引号" v2')
    first = compose_markdown(v, tags=["B标签", "a标签"])
    second = compose_markdown(v, tags=["B标签", "a标签"])
    assert first == second
    assert 'title: "标题 \\"带引号\\" v2"' in first
    # 标签按名称（码点序）排序 → 相同输入顺序无关，输出稳定。
    assert compose_markdown(v, tags=["a标签", "B标签"]) == first
    assert first.index('B标签') < first.index('a标签')


def test_compose_markdown_shape_note_and_source():
    v = _view(note="我的高亮笔记")
    doc = compose_markdown(v, tags=[])
    assert doc.startswith("---\n")
    assert doc.count("---") >= 2  # frontmatter 开闭
    assert "# 标题" in doc
    assert "我的高亮笔记" in doc
    assert "[原文](https://example.com/a)" in doc
    # 无笔记时正文不出现空段占位。
    empty = compose_markdown(_view(note=""), tags=[])
    assert "我的高亮笔记" not in empty


def test_export_endpoint_roundtrip_and_404(client):
    created = client.post(
        "/api/v1/library/bookmarks",
        json={
            "url": "https://example.com/md",
            "title": "导出测试",
            "note": "正文说明",
        },
    ).json()
    item_uuid = created["ref"].split(":", 1)[1]
    response = client.get(f"/api/v1/library/bookmarks/{item_uuid}/export.md")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert 'attachment' in response.headers["content-disposition"]
    body = response.text
    assert 'title: "导出测试"' in body
    assert "https://example.com/md" in body

    # 未知条目 → 稳定 404 信封。
    missing = client.get("/api/v1/library/bookmarks/00000000-0000-0000-0000-000000000000/export.md")
    assert missing.status_code == 404

    # 两次导出字节级一致（确定性）。
    again = client.get(f"/api/v1/library/bookmarks/{item_uuid}/export.md")
    assert again.content == response.content
    assert not re.search(r"\r\n", body)
