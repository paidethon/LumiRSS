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
# N126：被阻止的外链媒体清单上界（ingest 时如实记录，超出部分丢弃）。
_MAX_BLOCKED_MEDIA = 20
# 记录外链媒体的标签（src 属性；外链图片/音视频 = 跟踪与混合内容源）。
_MEDIA_TAGS = frozenset({"img", "video", "audio", "source", "track", "figure"})

# Dropped together with all of their content — same policy as
# article_sanitize so stored mail HTML is independently safe against
# parser-differential smuggling (mXSS carriers like math/template).
_DROP_WITH_CONTENT = frozenset(
    {
        "script", "style", "noscript", "iframe", "frame", "frameset",
        "object", "embed", "applet", "svg", "math", "canvas", "template",
        "form", "input", "button", "select", "option", "optgroup",
        "textarea", "label", "fieldset", "legend", "datalist", "output",
        "video", "audio", "source", "track", "base", "meta", "link",
        "title", "head", "dialog", "slot", "xmp", "plaintext", "noembed",
        "noframes",
    }
)


# Unsafe void elements (never carry an end tag): drop the tag itself —
# incrementing the skip depth here would swallow the rest of the mail.
_DROP_VOID = frozenset({"img", "input", "base", "meta", "link", "source", "track", "embed", "param", "area", "col", "wbr"})


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skip_depth = 0
        self._open_stack: list[str] = []
        # N126：被剥离的外链媒体 URL（有界；供 blocked_media_json 落库）。
        self.blocked_media: list[str] = []

    def _record_blocked(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """记录将被剥离的外链媒体 src（http/https 与协议相对地址）。"""
        if len(self.blocked_media) >= _MAX_BLOCKED_MEDIA:
            return
        if tag not in _MEDIA_TAGS:
            return
        for name, value in attrs:
            if name is None or name.lower() not in ("src", "poster") or not value:
                continue
            candidate = value.strip()
            lowered = candidate.lower()
            if lowered.startswith(("http://", "https://", "//")):
                self.blocked_media.append(candidate[:500])
                if len(self.blocked_media) >= _MAX_BLOCKED_MEDIA:
                    return

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _DROP_VOID or tag in _DROP_WITH_CONTENT or tag not in _ALLOWED_TAGS:
            # N126：先记录被剥离元素上的外链媒体（跟踪像素/远程图片）。
            self._record_blocked(tag, attrs)
        if tag in _DROP_VOID:
            return
        if tag in _DROP_WITH_CONTENT:
            self._skip_depth += 1
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
        # Void members never opened a skip region — a stray `</base>` must
        # not close an unrelated dropped container (independent review).
        if tag in _DROP_VOID:
            return
        if tag in _DROP_WITH_CONTENT and self._skip_depth > 0:
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


def sanitize_email_html_with_blocked(raw: str) -> tuple[str, list[str]]:
    """N126：净化 + 被阻止的外链媒体清单（有界 ≤20，去重保序）。"""
    if not isinstance(raw, str):
        return "", []
    if len(raw.encode("utf-8", errors="replace")) > _MAX_INPUT_BYTES:
        raw = raw[:_MAX_INPUT_BYTES]
    parser = _Sanitizer()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:
        # Unparseable markup degrades to escaped text, never a crash.
        return "<p>[无法解析的邮件正文]</p>", []
    seen: set[str] = set()
    blocked: list[str] = []
    for url in parser.blocked_media:
        if url in seen:
            continue
        seen.add(url)
        blocked.append(url)
    return "".join(parser.out), blocked


def sanitize_email_html(raw: str) -> str:
    """Strip an email body down to safe presentational HTML."""
    cleaned, _blocked = sanitize_email_html_with_blocked(raw)
    return cleaned


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
