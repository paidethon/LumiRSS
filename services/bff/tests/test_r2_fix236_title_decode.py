"""FIX-236 — 标题实体只按约定解码恰好一次（BASELINE 验证）。

排查结论（诚实基线）：后端没有任何「标题实体被重复解码」的路径——

1. FreshRSS greader 通道：适配器把 ``title`` **原样透传**（无任何
   unescape；greader 契约是 HTML 转义形式，唯一一次解码发生在最终
   渲染端），``&amp;lt;`` 不会被变成 ``<``；
2. feed 预览（feedparser）：XML 实体恰好解码一次；
3. Netscape 书签导入：``html.unescape`` 恰好一次（先剥离真实标签再
   解码，实体转义的标签文本不解体为可执行标记）；
4. 正文转文本（html_to_text）：convert_charrefs 单次解码。

本文件以单向解码往返测试钉住这四个边界：``&amp;lt;`` 形态的边界
恰好变成 ``&lt;``，绝不产生 ``<``（不生成 HTML 形态文本）。
"""

from lumirss.adapters.freshrss import FreshRSSAdapter, html_to_text
from lumirss.bookmarks_io import parse_netscape
from lumirss.feed_preview import parse_feed_document


def test_greader_title_is_relayed_verbatim_no_decode():
    """greader 通道：标题原样透传——`&amp;lt;` 保持 `&amp;lt;`，
    不被解码成 `&lt;` 更不会变成 `<`（唯一一次解码在渲染端）。"""
    item = {
        "id": "tag:google.com,2005:reader/item/0000000000000001",
        "title": "A &amp;lt; B &amp; C",
        "origin": {"streamId": "feed/1", "title": "源"},
        "summary": {"content": "<p>正文</p>"},
    }
    base = FreshRSSAdapter._common_fields(item)
    assert base is not None
    assert base["title"] == "A &amp;lt; B &amp; C"


def test_greader_title_shape_anomalies_stay_text_not_html():
    """含实体引用的 feed 标题/作者同样原样透传，不产生 HTML 形态。"""
    item = {
        "id": "1",
        "title": "已转义标题",
        "author": "a &amp;lt; b@example.com",
        "origin": {"streamId": "feed/1", "title": "源 &amp; 名"},
    }
    base = FreshRSSAdapter._common_fields(item)
    assert base["title"] == "已转义标题"
    assert base["author"] == "a &amp;lt; b@example.com"
    assert base["feed_title"] == "源 &amp; 名"
    assert "<" not in (base["title"] + str(base["author"]) + base["feed_title"])


def test_feedparser_title_decoded_exactly_once():
    """feed 预览：XML 实体恰好解码一次——文档里的 `&amp;lt;` 变成
    `&lt;`（文本边界），绝不是 `<`。"""
    rss = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<rss version="2.0"><channel>'
        b"<title>A &amp;lt; B</title>"
        b"<link>https://example.com/</link>"
        b"<description>desc</description>"
        b"</channel></rss>"
    )
    title, _site_url, _description, feed_format = parse_feed_document(rss)
    assert feed_format == "rss"
    assert title == "A &lt; B"


def test_netscape_bookmark_title_single_decode_round_trip():
    """Netscape 导入：文件里 `&amp;amp;lt;`（作者原文 `&lt;` 的 HTML
    编码）解码恰好一次得 `&lt;`；绝不二次解码成 `<`。"""
    text = (
        "<DL><p>"
        '<DT><A HREF="https://example.com/x" ADD_DATE="1700000000">'
        "A &amp;amp;lt; B &amp; C</A>"
        "</DL><p>"
    )
    items = parse_netscape(text)
    assert len(items) == 1
    assert items[0].title == "A &amp;lt; B & C"
    assert "<" not in items[0].title


def test_html_to_text_decodes_entities_once():
    """正文转文本：convert_charrefs 单次解码——`&amp;lt;` 变成文本
    `&lt;`；不会出现标签形态。"""
    assert html_to_text("<p>x &amp;lt; y</p>") == "x &lt; y"
    assert html_to_text("<p>a &amp; b</p>") == "a & b"
