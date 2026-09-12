"""Server-side article extraction (readability-style) for web clipping.

Replaces the trust-the-browser model: the BFF derives the article body
itself, so stored clip content is server-produced (P0-03). Standard
library only (html.parser), heuristic scoring in the spirit of Mozilla
Readability:

- drop non-content chrome (nav/header/footer/aside/form/...) and every
  script/style-ish container up front;
- score candidate containers by the text mass of the paragraphs they
  directly hold (length + punctuation density), weighted by class/id
  hints (positive: article/body/content/entry/main/story/post; negative:
  comment/meta/sidebar/footer/promo/advert/related/social/...);
- pick the highest-scoring container (score-propagated to parent and
  grandparent like the original algorithm), serialize its INNER HTML and
  let the caller sanitize it; a plain-text version is derived alongside.

Title comes from og:title / <title> / <h1>; byline from
meta[name=author] or byline/author-marked elements.

Hostile input is bounded: the tree build caps depth, serialization is
iterative (no recursion), and extraction is best-effort — it never
raises on content.
"""

import html as html_
import re
from dataclasses import dataclass
from html.parser import HTMLParser

_MAX_BUILD_DEPTH = 500
_MAX_TITLE_LENGTH = 500
_MAX_BYLINE_LENGTH = 200

# Chrome dropped WITH content. "head" is kept out of this list on
# purpose: meta/title live there and feed title/byline extraction, and
# they can never win content scoring (their tags are not containers).
_CHROME_TAGS = frozenset(
    {
        "script", "style", "noscript", "template", "svg", "math", "iframe",
        "frame", "frameset", "object", "embed", "applet", "canvas", "nav",
        "aside", "header", "footer", "form", "button", "input", "select",
        "textarea", "label", "option", "video", "audio", "source", "track",
        "dialog", "link", "base",
    }
)

_POSITIVE_RE = re.compile(
    r"article|body|content|entry|main|story|post|text", re.IGNORECASE
)
_NEGATIVE_RE = re.compile(
    r"comment|meta|footer|footnote|sidebar|widget|promo|advert|ads|social|"
    r"related|share|sharrre|subscribe|newsletter|signup|menu|nav|header|"
    r"credit|copyright|byline-source",
    re.IGNORECASE,
)
_BYLINE_RE = re.compile(r"byline|author", re.IGNORECASE)

_PARAGRAPH_TAGS = frozenset({"p", "pre", "blockquote"})
_CONTAINER_TAGS = frozenset({"div", "article", "section", "main", "td", "body"})


@dataclass(frozen=True)
class ExtractedArticle:
    """Server-derived article: raw inner HTML (pre-sanitization) + meta."""

    title: str
    byline: str | None
    content_html: str
    content_text: str


# -- lightweight DOM ------------------------------------------------------
# node: {"tag": str, "attrs": dict[str, str], "children": list[node | str]}


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = {"tag": "#root", "attrs": {}, "children": []}
        self._stack = [self.root]
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if self._skip_depth > 0:
            if tag not in ("br", "hr", "img", "wbr", "col", "meta", "link", "input", "source", "track"):
                self._skip_depth += 1
            return
        if tag in _CHROME_TAGS:
            if tag not in ("br", "hr", "img", "wbr", "col", "meta", "link", "input", "source", "track"):
                self._skip_depth += 1
            return
        if len(self._stack) >= _MAX_BUILD_DEPTH:
            return  # flatten: children of over-deep nodes attach to the cap node
        node = {
            "tag": tag,
            "attrs": {k: (v or "") for k, v in attrs if k},
            "children": [],
        }
        self._stack[-1]["children"].append(node)
        if tag not in ("br", "hr", "img", "wbr", "col"):
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        if self._skip_depth > 0 or tag in _CHROME_TAGS:
            return
        if len(self._stack) >= _MAX_BUILD_DEPTH:
            return
        node = {
            "tag": tag,
            "attrs": {k: (v or "") for k, v in attrs if k},
            "children": [],
        }
        self._stack[-1]["children"].append(node)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self._skip_depth > 0:
            self._skip_depth -= 1
            return
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index]["tag"] == tag:
                del self._stack[index:]
                return

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        if data:
            self._stack[-1]["children"].append(data)


def _build_tree(raw_html: str):
    builder = _TreeBuilder()
    try:
        builder.feed(raw_html)
        builder.close()
    except Exception:
        pass  # best-effort: keep whatever parsed
    return builder.root


def _node_text(node) -> str:
    parts: list[str] = []

    def walk(current) -> None:  # closure recursion depth is build-capped
        for child in current["children"]:
            if isinstance(child, str):
                parts.append(child)
            else:
                walk(child)

    walk(node)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


# -- scoring --------------------------------------------------------------


def _class_hint(node) -> float:
    marker = " ".join(
        [node["attrs"].get("class", ""), node["attrs"].get("id", "")]
    )
    if not marker.strip():
        return 1.0
    if _NEGATIVE_RE.search(marker):
        return 0.15
    if _POSITIVE_RE.search(marker):
        return 1.6
    return 1.0


def _paragraph_score(node) -> float:
    text = _node_text(node)
    if len(text) < 25:
        return 0.0
    score = 1.0
    score += min(3.0, text.count(",") + text.count("，"))
    score += min(3.0, len(text) / 100.0)
    return score


def _score_candidates(root):
    """Score containers by their direct paragraphs, Readability-style."""
    scores: dict[int, float] = {}
    parents: dict[int, object] = {}

    def walk(node, parent, grandparent) -> None:
        if not isinstance(node, dict) or node.get("tag") == "#root":
            for child in node["children"]:
                if not isinstance(child, str):
                    walk(child, node, node)
            return
        if node["tag"] in _PARAGRAPH_TAGS:
            score = _paragraph_score(node)
            if score > 0:
                for target, weight in ((parent, 1.0), (grandparent, 0.5)):
                    if isinstance(target, dict) and target.get("tag") != "#root":
                        key = id(target)
                        parents[key] = target
                        # Readability weights the CONTAINER's class/id
                        # (article-content vs sidebar decides the winner).
                        scores[key] = scores.get(key, 0.0) + score * weight * _class_hint(target)
        for child in node["children"]:
            if not isinstance(child, str):
                walk(child, node, parent)

    walk(root, None, None)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [(parents[key], value) for key, value in ranked]


# -- serialization (iterative) --------------------------------------------


def _serialize_inner(node) -> str:
    """Iterative inner-HTML serialization (no recursion on hostile input).

    Stack entries: (node_or_text, unused, opened). A container pushes
    its close-marker FIRST, then its children in reverse, so children
    pop in document order and the close tag lands after the last one.
    """
    out: list[str] = []
    void = ("br", "hr", "img", "wbr", "col")
    stack: list[tuple[object, int, bool]] = [(node, 0, False)]
    while stack:
        current, _index, opened = stack.pop()
        if isinstance(current, str):
            out.append(html_.escape(current, quote=False))
            continue
        tag = current["tag"]
        if opened:
            out.append(f"</{tag}>")
            continue
        attrs = "".join(
            f' {k}="{html_.escape(v, quote=True)}"'
            for k, v in current["attrs"].items()
            if v
        )
        if tag in void:
            out.append(f"<{tag}{attrs}>")
            continue
        out.append(f"<{tag}{attrs}>")
        stack.append((current, 0, True))
        for child in reversed(current["children"]):
            stack.append((child, 0, False))
    return "".join(out)


# -- metadata --------------------------------------------------------------


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _extract_title(root) -> str:
    for meta_name in ("og:title", "twitter:title"):
        for node in _iter_tag(root, "meta"):
            key = node["attrs"].get("property", "") or node["attrs"].get("name", "")
            if key.lower() == meta_name:
                title = _collapse(node["attrs"].get("content", ""))
                if title:
                    return title
    for title_node in _iter_tag(root, "title"):
        title = _collapse(_node_text(title_node))
        if title:
            return title
    for h1 in _iter_tag(root, "h1"):
        title = _collapse(_node_text(h1))
        if title:
            return title
    return ""


def _extract_byline(root) -> str | None:
    for node in _iter_tag(root, "meta"):
        if node["attrs"].get("name", "").lower() == "author":
            byline = _collapse(node["attrs"].get("content", ""))
            if byline:
                return byline
    for node in _iter_all(root):
        marker = " ".join(
            [node["attrs"].get("class", ""), node["attrs"].get("rel", "")]
        )
        if _BYLINE_RE.search(marker) and "byline-source" not in marker.lower():
            byline = _collapse(_node_text(node))
            if byline and len(byline) <= 120:
                return byline
    return None


def _iter_tag(root, tag):
    for node in _iter_all(root):
        if node["tag"] == tag:
            yield node


def _iter_all(root):
    stack = [root]
    while stack:
        node = stack.pop()
        if isinstance(node, str):
            continue
        yield node
        for child in reversed(node["children"]):
            stack.append(child)


# -- entry point -----------------------------------------------------------


def extract_article(raw_html: str) -> ExtractedArticle:
    """Best-effort main-content extraction. Never raises on content."""
    root = _build_tree(raw_html)
    title = _extract_title(root)[:_MAX_TITLE_LENGTH]
    byline = _extract_byline(root)
    if byline:
        byline = byline[:_MAX_BYLINE_LENGTH]

    ranked = _score_candidates(root)
    best_node = None
    for candidate, score in ranked:
        if candidate["tag"] in _CONTAINER_TAGS and score >= 8.0:
            best_node = candidate
            break
    if best_node is None:
        body = next(_iter_tag(root, "body"), None)
        best_node = body if body is not None else root

    content_html = _serialize_inner(best_node)
    return ExtractedArticle(
        title=title,
        byline=byline,
        content_html=content_html,
        content_text=_node_text(best_node)[:512 * 1024],
    )
