"""Test E — html_to_text: deterministic text-only normalization.

Not a browser-grade HTML parser; the bar is: no tags, entities decoded,
paragraphs readable, script/style content gone.
"""

from lumirss.adapters.freshrss import html_to_text


def test_tags_entities_and_paragraphs():
    html = "<p>Hello &amp; LumiRSS</p><p>Second paragraph</p>"

    text = html_to_text(html)

    assert "Hello & LumiRSS" in text
    assert "Second paragraph" in text
    assert text.index("Hello & LumiRSS") < text.index("Second paragraph")
    assert "<p>" not in text and "</p>" not in text
    assert "&amp;" not in text


def test_script_and_style_content_is_dropped():
    html = (
        "<p>before</p>"
        "<script>alert(1)</script>"
        "<style>body{color:red}</style>"
        "<p>after</p>"
    )

    text = html_to_text(html)

    assert "alert(1)" not in text
    assert "color:red" not in text
    assert "before" in text
    assert "after" in text


def test_inline_tags_do_not_break_words():
    text = html_to_text('<p>开源，欢迎<a href="https://example.com">贡献</a>。</p>')

    assert text == "开源，欢迎贡献。"


def test_plain_text_passes_through():
    assert html_to_text("没有标签的纯文本。") == "没有标签的纯文本。"


def test_numeric_and_named_entities_are_decoded():
    text = html_to_text("<p>a &lt; b &#38; c</p>")

    assert text == "a < b & c"


def test_empty_and_whitespace_only_html():
    assert html_to_text("") == ""
    assert html_to_text("<p>  </p><div>\n</div>") == ""


def test_block_tags_produce_line_breaks_not_one_line():
    text = html_to_text("<p>one</p><div>two</div><li>three</li>")

    lines = [line for line in text.splitlines() if line.strip()]
    assert lines == ["one", "two", "three"]
