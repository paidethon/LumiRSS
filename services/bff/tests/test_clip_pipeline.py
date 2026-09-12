"""Server-side clip pipeline tests (phase2 recovery P0-03).

Covers the allow-list sanitizer against the full malicious-HTML matrix
(script/iframe/object/embed, event handlers, javascript:/data: URLs, CSS
expression, oversized, deeply nested), the readability-style extractor
over tricky HTML, and the URL-validation hop (OSError → stable error).
"""

import pytest

from lumirss.article_extract import extract_article
from lumirss.article_sanitize import sanitize_html

# --------------------------------------------------------------------------
# Sanitizer — malicious HTML matrix
# --------------------------------------------------------------------------


def test_script_and_container_tags_dropped_with_content():
    dirty = (
        "<p>safe</p><script>alert(1)</script><style>p{}</style>"
        "<iframe src='https://evil.example'></iframe>"
        "<object data='x'></object><embed src='x'>"
    )
    clean = sanitize_html(dirty)
    assert "safe" in clean
    assert "script" not in clean
    assert "alert" not in clean
    assert "iframe" not in clean
    assert "object" not in clean
    assert "embed" not in clean
    assert "style" not in clean


def test_event_handlers_dropped():
    dirty = '<p onclick="evil()" onmouseover="evil()" onerror="evil()">x</p><img src="https://a.example/i.png" onerror="evil()">'
    clean = sanitize_html(dirty)
    assert "onclick" not in clean.lower()
    assert "onmouseover" not in clean.lower()
    assert "onerror" not in clean.lower()
    assert "evil()" not in clean


def test_javascript_and_data_urls_dropped():
    dirty = (
        "<a href=\"javascript:alert(1)\">x</a>"
        "<a href=\"JAVASCRIPT:alert(1)\">y</a>"
        '<a href="java\tscript:alert(1)">z</a>'
        '<a href=" java\nscript:alert(1) ">w</a>'
        '<img src="data:text/html;base64,PHNjcmlwdD4=">'
        '<a href="vbscript:msgbox(1)">v</a>'
        '<a href="data:text/html,<b>x</b>">d</a>'
    )
    clean = sanitize_html(dirty)
    assert "javascript" not in clean.lower()
    assert "vbscript" not in clean.lower()
    assert "data:text/html" not in clean.lower()
    assert "alert(1)" not in clean


def test_safe_urls_and_data_images_kept():
    dirty = (
        '<a href="https://ok.example/page">link</a>'
        '<img src="data:image/png;base64,iVBORw0KGgo=" alt="px">'
        '<img src="https://img.example/cat.png" alt="cat">'
        '<a href="mailto:a@b.example">mail</a>'
    )
    clean = sanitize_html(dirty)
    assert 'href="https://ok.example/page"' in clean
    assert 'src="data:image/png;base64,iVBORw0KGgo="' in clean
    assert 'src="https://img.example/cat.png"' in clean
    assert 'href="mailto:a@b.example"' in clean
    # data:image/svg is scriptable and must never survive
    assert "svg" not in sanitize_html('<img src="data:image/svg+xml;base64,x">')


def test_css_expression_and_style_attributes_dropped():
    dirty = (
        '<p style="width: expression(alert(1)); background: url(javascript:alert(2))">x</p>'
        '<div style="behavior: url(evil.htc)">y</div>'
    )
    clean = sanitize_html(dirty)
    assert "expression" not in clean
    assert "style=" not in clean
    assert "behavior" not in clean


def test_comments_and_doctype_and_pi_dropped():
    dirty = "<!-- <script>alert(1)</script> --><!DOCTYPE html><p>x</p><?php evil(); ?>"
    clean = sanitize_html(dirty)
    assert "<script" not in clean
    assert "alert" not in clean
    assert "DOCTYPE" not in clean
    assert "<?php" not in clean
    assert "<p>x</p>" in clean


def test_unknown_tags_unwrapped_children_kept():
    dirty = "<custom-widget><p>kept</p></custom-widget><marquee>text kept</marquee>"
    clean = sanitize_html(dirty)
    assert "<p>kept</p>" in clean
    assert "text kept" in clean
    assert "custom-widget" not in clean
    assert "marquee" not in clean


def test_relative_urls_resolved_against_base():
    clean = sanitize_html(
        '<a href="/page">x</a><img src="../img.png">',
        base_url="https://origin.example/a/b/",
    )
    assert 'href="https://origin.example/page"' in clean
    assert 'src="https://origin.example/a/img.png"' in clean  # ../ resolved
    # protocol-relative pointers must not stay same-origin-relative
    clean2 = sanitize_html('<img src="//cdn.example/x.png">', base_url="https://origin.example/")
    assert 'src="https://cdn.example/x.png"' in clean2


def test_anchors_get_safe_rel_and_target():
    clean = sanitize_html('<a href="https://ok.example">x</a>')
    assert 'rel="noopener noreferrer nofollow"' in clean
    assert 'target="_blank"' in clean


def test_oversized_input_truncated_but_well_formed():
    dirty = "<div>" + "<p>chunk-of-content </p>" * 200_000 + "</div>"
    clean = sanitize_html(dirty)
    # Cap plus bounded overshoot: one data chunk + pending closers
    # (bounded by the 60-level depth cap).
    assert len(clean.encode("utf-8")) <= 2 * 1024 * 1024 + 1024
    assert clean.count("<div>") <= 1
    assert clean.count("<p>") == clean.count("</p>")  # balanced after cap
    assert clean.endswith("</div>")


def test_deeply_nested_input_flattened_not_fatal():
    dirty = "<div>" * 5000 + "deep text" + "</div>" * 5000
    clean = sanitize_html(dirty)
    assert "deep text" in clean
    assert clean.count("<div>") <= 61  # depth cap + slack
    # recursion safety: builder/serializer are iterative


def test_entities_decoded_and_reescaped():
    dirty = "<p&gt;not-a-tag</p&gt><p>a &lt; b &amp; c</p><img alt='&quot;q&quot;' src='https://i.example/x.png'>"
    clean = sanitize_html(dirty)
    assert "a &lt; b &amp; c" in clean
    assert 'alt="&quot;q&quot;"' in clean


# --------------------------------------------------------------------------
# Extractor — tricky HTML
# --------------------------------------------------------------------------


def _article_html(body: str, *, title: str = "文章标题", og: str | None = None) -> str:
    og_meta = f'<meta property="og:title" content="{og}">' if og else ""
    return (
        "<html><head>" + og_meta + f"<title>{title}</title>"
        '<meta name="author" content="张三"></head><body>'
        "<nav><a href='/nav'>站点导航</a></nav>"
        f"<article>{body}</article>"
        "<footer>版权所有 相关推荐</footer></body></html>"
    )


def test_extracts_main_content_title_byline():
    paragraphs = "".join(f"<p>这是正文第{i}段，包含足够的文字长度用于评分，内容围绕主题展开。</p>" for i in range(6))
    article = extract_article(_article_html(paragraphs))
    assert article.title == "文章标题"
    assert article.byline == "张三"
    assert "这是正文第1段" in article.content_html
    assert "站点导航" not in article.content_html
    assert "版权所有" not in article.content_html


def test_og_title_wins_over_title_tag():
    paragraphs = "<p>" + "正文内容足够长。" * 10 + "</p>"
    article = extract_article(_article_html(paragraphs, title="站点默认标题", og="OG 真标题"))
    assert article.title == "OG 真标题"


def test_h1_fallback_title():
    html = "<html><body><h1>大标题</h1><p>" + "正文。" * 40 + "</p></body></html>"
    article = extract_article(html)
    assert article.title == "大标题"


def test_best_container_wins_over_sidebar():
    sidebar = "<div class='sidebar'><p>" + "侧栏推荐内容。" * 30 + "</p></div>"
    main = "<div class='article-content'><p>" + "真正的深度报道正文，讲述一个完整的故事，句子足够长有标点。" * 30 + "</p></div>"
    article = extract_article(f"<html><body>{sidebar}{main}</body></html>")
    assert "真正的深度报道正文" in article.content_html
    assert "侧栏推荐内容" not in article.content_html


def test_malformed_truncated_html_never_raises():
    for dirty in (
        "<html><body><p>未闭合的正文",
        "<div><span><b>嵌套未闭合<p>text",
        "",
        "纯文本，没有标签。",
        "<<<<>>>><p><p><p>x",
        "\x00\x01控制字符<p>正文</p>",
    ):
        article = extract_article(dirty)
        assert isinstance(article.content_html, str)


def test_deeply_nested_html_bounded():
    html = "<div>" * 3000 + "<p>" + "深嵌套正文。" * 50 + "</p>" + "</div>" * 3000
    article = extract_article(html)  # must not RecursionError
    assert "深嵌套正文" in article.content_text


def test_script_content_never_reaches_extraction():
    html = "<html><body><script>var secret='x'</script><p>" + "正文内容。" * 30 + "</p></body></html>"
    article = extract_article(html)
    assert "secret" not in article.content_html
    assert "secret" not in article.content_text


# --------------------------------------------------------------------------
# validate_hop — OSError / resolution failures become stable errors
# --------------------------------------------------------------------------


def test_validate_hop_dns_failure_maps_to_clip_error():
    import asyncio

    from lumirss.clip_fetch import ClipFetchError, validate_hop

    async def failing_resolver(host, port):
        raise OSError(5, "weird resolver breakdown")  # not socket.gaierror

    with pytest.raises(ClipFetchError) as excinfo:
        asyncio.run(validate_hop("https://broken.example/", resolver=failing_resolver))
    assert excinfo.value.reason == "dns_failure"


def test_validate_hop_unsafe_address_maps_to_forbidden():
    import asyncio

    from lumirss.clip_fetch import ClipForbidden, validate_hop

    async def private_resolver(host, port):
        return ["10.1.2.3"]

    with pytest.raises(ClipForbidden) as excinfo:
        asyncio.run(validate_hop("https://rebind.example/", resolver=private_resolver))
    assert excinfo.value.reason == "unsafe_address"
