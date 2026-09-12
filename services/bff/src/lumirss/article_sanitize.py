"""Allow-list HTML sanitizer for server-side clip content (P0-03).

Input is untrusted article HTML fetched by the BFF; output is a bounded,
allow-list subset of HTML that keeps the visual shape of an article and
is DOMPurify-compatible: passing this output through DOMPurify (the
architecture's final render boundary, unchanged) must be a no-op. The
sanitizer makes the STORED content itself safe instead of trusting the
browser to have cleaned it.

Rules:

- tags: allow-list only. Unknown tags are unwrapped (children kept);
  dangerous containers (script/style/iframe/object/embed/...) are
  dropped WITH their content; comments, doctypes, CDATA and processing
  instructions are dropped entirely;
- attributes: allow-list per tag (``a[href,title]``, ``img[src,...]``,
  ``td/th[colspan,rowspan]``, ...). Any attribute whose name starts with
  ``on`` is unconditionally refused, and ``style`` is never allowed
  (kills CSS expression()/url() tricks) — everything else falls to the
  allow-list;
- URLs (href/src): http/https/relative only, plus ``mailto:`` on href
  and ``data:image/<safe type>;base64,`` on img. All whitespace and
  control characters are stripped from the value before scheme matching
  (defeats ``java\\nscript:`` and friends). Relative URLs are resolved
  against ``base_url`` when provided so stored content never contains
  same-origin-relative pointers;
- nesting is capped: beyond ``_MAX_DEPTH`` only text survives (deeply
  nested bombs flatten instead of exploding output or recursing);
- output size is capped at ``_MAX_OUTPUT_BYTES``; truncation closes the
  open tag stack so the result stays well-formed.

Standard library only (html.parser); serialization is iterative — no
recursion on hostile input.
"""

import html
import re
from html.parser import HTMLParser

_MAX_DEPTH = 60
_MAX_OUTPUT_BYTES = 2 * 1024 * 1024

# Dropped together with all of their content — no unwrapping.
_DROP_WITH_CONTENT = frozenset(
    {
        "script", "style", "noscript", "iframe", "frame", "frameset",
        "object", "embed", "applet", "svg", "math", "canvas", "template",
        "form", "input", "button", "select", "option", "optgroup",
        "textarea", "label", "fieldset", "legend", "datalist", "output",
        "video", "audio", "source", "track", "base", "meta", "link",
        "title", "head", "dialog", "slot", "portal", "nosframe", "xmp",
        "plaintext", "noembed", "noframes",
    }
)

_ALLOWED_TAGS = frozenset(
    {
        "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6",
        "ul", "ol", "li", "blockquote", "pre", "code",
        "em", "strong", "i", "b", "u", "s", "del", "ins", "mark",
        "small", "sub", "sup", "a", "img", "figure", "figcaption",
        "span", "div", "article", "section", "main",
        "table", "thead", "tbody", "tfoot", "tr", "th", "td",
        "caption", "colgroup", "col",
        "abbr", "cite", "q", "dfn", "kbd", "samp", "var", "time",
        "wbr", "address", "details", "summary",
    }
)

_VOID_TAGS = frozenset({"br", "hr", "img", "wbr", "col"})

_ALLOWED_ATTRS: dict[str, frozenset[str]] = {
    "a": frozenset({"href", "title"}),
    "img": frozenset({"src", "alt", "title", "width", "height"}),
    "th": frozenset({"colspan", "rowspan"}),
    "td": frozenset({"colspan", "rowspan"}),
    "col": frozenset({"span"}),
    "time": frozenset({"datetime"}),
    "details": frozenset({"open"}),
}

# href keeps mailto:, src allows inline raster images only (never svg —
# svg can carry script). Anything else must be http(s) or relative.
_URL_ATTRS: dict[str, frozenset[str]] = {
    "href": frozenset({"http", "https", "mailto"}),
    "src": frozenset({"http", "https"}),
}

_DATA_IMAGE_RE = re.compile(
    r"^data:image/(?:png|jpe?g|gif|webp|bmp|x-icon|vnd\.microsoft\.icon);base64,[a-z0-9+/=]+$",
    re.IGNORECASE,
)
_SCHEME_RE = re.compile(r"^([a-z][a-z0-9+.\-]*):")


def _safe_url(value: str, *, tag: str, attr: str, base_url: str | None) -> str | None:
    """Normalize and policy-check one URL attribute value."""
    # Strip ALL whitespace (incl. embedded tabs/newlines/controls that
    # browsers historically ignored inside URLs) before scheme matching.
    cleaned = "".join(value.split())
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if tag == "img" and _DATA_IMAGE_RE.match(lowered):
        return cleaned
    match = _SCHEME_RE.match(lowered)
    if match:
        allowed = _URL_ATTRS.get(attr, frozenset({"http", "https"}))
        if match.group(1) not in allowed:
            return None
    if base_url:
        import urllib.parse

        try:
            resolved = urllib.parse.urljoin(base_url, cleaned)
        except ValueError:
            return None
        return resolved[:4096]
    return cleaned[:4096]


def _safe_attrs(tag: str, attrs: list[tuple[str, str | None]], *, base_url: str | None) -> str:
    parts: list[str] = []
    allowed = _ALLOWED_ATTRS.get(tag, frozenset())
    for name, raw in attrs:
        if not name or name[:1] in ("on",):
            continue  # event handlers are refused unconditionally
        lowered = name.lower()
        if lowered != name:
            continue  # case-mangled duplicates (ONCLICK) are not on the list
        if lowered.startswith("on") or lowered in ("style", "srcset"):
            continue
        if lowered not in allowed:
            continue
        value = raw if raw is not None else ""
        if lowered in ("href", "src"):
            value = _safe_url(value, tag=tag, attr=lowered, base_url=base_url)
            if value is None:
                continue
            if lowered == "href":
                parts.append(f' {lowered}="{html.escape(value, quote=True)}" rel="noopener noreferrer nofollow" target="_blank"')
                continue
        parts.append(f' {lowered}="{html.escape(value, quote=True)}"')
    return "".join(parts)


class _Sanitizer(HTMLParser):
    def __init__(self, *, base_url: str | None) -> None:
        super().__init__(convert_charrefs=True)
        self._base_url = base_url
        self._out: list[str] = []
        self._size = 0
        self._truncated = False
        self._stack: list[tuple[str, bool]] = []  # (tag, emitted)
        self._skip_depth = 0  # inside a dropped-with-content subtree

    # -- output helpers ---------------------------------------------------
    def _emit(self, text: str) -> None:
        if self._truncated:
            return
        self._out.append(text)
        self._size += len(text.encode("utf-8"))
        if self._size > _MAX_OUTPUT_BYTES:
            self._truncated = True

    # -- parser events ----------------------------------------------------
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if self._skip_depth > 0:
            if tag not in _VOID_TAGS:
                self._skip_depth += 1
            return
        if tag in _DROP_WITH_CONTENT:
            if tag not in _VOID_TAGS:
                self._skip_depth += 1
            return
        if tag not in _ALLOWED_TAGS:
            return  # unknown: unwrap, keep children
        emitted = len(self._stack) < _MAX_DEPTH and not self._truncated
        if emitted:
            self._emit(f"<{tag}{_safe_attrs(tag, attrs, base_url=self._base_url)}>")
        if tag not in _VOID_TAGS:
            self._stack.append((tag, emitted))

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        if tag in _VOID_TAGS or tag not in _ALLOWED_TAGS:
            self.handle_starttag(tag, attrs)
            return
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if tag in _VOID_TAGS or tag not in _ALLOWED_TAGS:
            return
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                while len(self._stack) > index:
                    open_tag, emitted = self._stack.pop()
                    if emitted:
                        # Closers are emitted even past truncation: the
                        # output must stay well-formed after the cap.
                        # (Accounted, but never re-triggers truncation —
                        # pending closers are bounded by the depth cap.)
                        self._out.append(f"</{open_tag}>")
                        self._size += len(self._out[-1].encode("utf-8"))
                return
        # stray close tag: ignore

    def handle_data(self, data):
        if self._skip_depth > 0 or self._truncated:
            return
        self._emit(html.escape(data, quote=False))

    def handle_comment(self, data):  # noqa: D401 — parser callback
        return

    def handle_decl(self, decl):
        return

    def handle_pi(self, data):
        return

    def unknown_decl(self, data):
        return

    # -- result -----------------------------------------------------------
    def result(self) -> str:
        # Closing the open stack happens even when truncated: the output
        # must stay well-formed past the size boundary. Pending closers
        # are bounded by the depth cap, so the overshoot is bounded.
        while self._stack:
            _tag, emitted = self._stack.pop()
            if emitted:
                self._out.append(f"</{_tag}>")
                self._size += len(self._out[-1].encode("utf-8"))
        return "".join(self._out)


def sanitize_html(raw_html: str, *, base_url: str | None = None) -> str:
    """Reduce untrusted article HTML to the Lumi allow-list subset."""
    sanitizer = _Sanitizer(base_url=base_url)
    try:
        sanitizer.feed(raw_html)
        sanitizer.close()
    except Exception:  # malformed input must never 500 the pipeline
        pass  # keep whatever was emitted before the parser gave up
    return sanitizer.result()
