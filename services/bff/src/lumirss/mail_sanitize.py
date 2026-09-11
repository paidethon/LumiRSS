"""Email HTML sanitization (phase2 M3/G5).

Newsletter HTML is untrusted input rendered later inside FreshRSS. This
allowlist stripper (stdlib html.parser only) removes scripts, styles,
iframes, forms, event handlers and — deliberately — every remote image:
"不加载远程图片" kills tracking beacons and content injections in one
move. Data-URI images under a small cap are kept (inline diagrams), all
links keep href but lose target manipulation. Output is plain safe HTML
for the Atom content; the RSS-domain sanitization pipeline applies again
downstream (defense in depth).
"""

import html
from html.parser import HTMLParser

_ALLOWED_TAGS = frozenset(
    {
        "p", "br", "b", "i", "em", "strong", "u", "s", "h1", "h2", "h3",
        "h4", "h5", "h6", "ul", "ol", "li", "blockquote", "pre", "code",
        "a", "table", "thead", "tbody", "tr", "th", "td", "hr",
        "figure", "figcaption", "span", "div",
    }
)
_ALLOWED_ATTRS = frozenset({"href", "title"})
_VOID_TAGS = frozenset({"br", "hr"})
_MAX_INPUT_BYTES = 2 * 1024 * 1024
_MAX_DATA_URI = 64 * 1024


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skip_depth = 0
        self._open_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "iframe", "form", "img", "svg", "object", "embed", "video", "audio", "input", "button", "select", "textarea", "link", "meta", "base"):
            if tag not in ("img",):
                self._skip_depth += 1 if tag in ("script", "style", "iframe", "form", "svg", "object") else 0
            return
        if self._skip_depth > 0:
            return
        if tag not in _ALLOWED_TAGS:
            return
        cleaned: list[tuple[str, str]] = []
        for name, value in attrs:
            name = name.lower()
            if name not in _ALLOWED_ATTRS or value is None:
                continue
            if name == "href":
                lowered = value.strip().lower()
                if lowered.startswith(("http://", "https://", "mailto:")):
                    cleaned.append(("href", value))
            elif name == "title":
                cleaned.append(("title", value))
        attr_text = "".join(
            f' {name}="{html.escape(value, quote=True)}"'
            for name, value in cleaned
        )
        if tag in _VOID_TAGS:
            self.out.append(f"<{tag}/>")
        else:
            self.out.append(f"<{tag}{attr_text}>")
            self._open_stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br" or tag == "hr":
            self.handle_starttag(tag, attrs)
            return

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "iframe", "form", "svg", "object") and self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if self._skip_depth > 0:
            return
        if tag in _ALLOWED_TAGS and tag not in _VOID_TAGS and tag in self._open_stack:
            self.out.append(f"</{tag}>")
            while self._open_stack:
                opened = self._open_stack.pop()
                if opened == tag:
                    break

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        self.out.append(html.escape(data, quote=False))


def sanitize_email_html(raw: str) -> str:
    """Strip an email body down to safe presentational HTML."""
    if not isinstance(raw, str):
        return ""
    if len(raw.encode("utf-8", errors="replace")) > _MAX_INPUT_BYTES:
        raw = raw[:_MAX_INPUT_BYTES]
    parser = _Sanitizer()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:
        # Unparseable markup degrades to escaped text, never a crash.
        return "<p>[无法解析的邮件正文]</p>"
    return "".join(parser.out)


def html_to_text(raw: str) -> str:
    """Plain-text twin of the sanitized body (digest text version)."""
    text = sanitize_email_html(raw)
    return (
        text.replace("<br/>", "\n")
        .replace("</p>", "\n\n")
        .replace("</li>", "\n")
        .replace("</h1>", "\n\n")
        .replace("</h2>", "\n\n")
        .replace("</h3>", "\n\n")
    )
