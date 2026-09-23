"""Encoding diagnostics (N033) — declared vs detected charset on the
bounded feed body, with an honest mojibake risk flag and a masked sample.

No chardet dependency (deliberately): the detection is a LIGHT heuristic
that Lumi can explain line by line —

1. BOM (utf-8-sig / utf-16 le+be / utf-32 le+be) — physical mark, highest
   confidence;
2. declared charset, verified by actually decoding: XML declaration
   ``<?xml ... encoding="..."?>``, HTML ``<meta charset>``, then the HTTP
   Content-Type header;
3. strict UTF-8 validity (the overwhelmingly common case for feeds);
4. ``unknown`` — the bytes are not valid UTF-8 and nothing declared could
   decode them cleanly. We do NOT guess (no fabrication).

``inspect_encoding`` never raises on hostile input; every text output is
bounded (sample ≤ 200 chars).
"""

import re

_SAMPLE_CHARS = 200
_SNIFF_BYTES = 2048

_BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\xfe\xff", "utf-16-be"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
)

_XML_ENCODING_RE = re.compile(
    rb"""<\?xml[^>]*?encoding=["']([A-Za-z0-9._-]+)["']""", re.IGNORECASE
)
_META_CHARSET_RE = re.compile(
    rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9._-]+)""", re.IGNORECASE
)
_HEADER_CHARSET_RE = re.compile(r"""charset=\s*"?([A-Za-z0-9._-]+)""", re.IGNORECASE)

# codec aliases we normalize so comparisons do not produce fake mismatches
_CODEC_ALIASES = {
    "utf8": "utf-8",
    "utf-8": "utf-8",
    "utf-8-sig": "utf-8-sig",
    "unicode-1-1-utf-8": "utf-8",
    "gb2312": "gbk",
    "gbk": "gbk",
    "gb18030": "gb18030",
    "big5": "big5",
    "shift_jis": "shift_jis",
    "shift-jis": "shift_jis",
    "iso-8859-1": "latin-1",
    "latin1": "latin-1",
}


def normalize_codec(name: str | None) -> str | None:
    """Lowercased canonical codec name (unknown names pass through)."""
    if not name:
        return None
    lowered = name.strip().strip('"\'').lower()
    return _CODEC_ALIASES.get(lowered, lowered)


def _declared_from_body(body: bytes) -> tuple[str | None, str | None]:
    """(charset, method) from BOM / XML declaration / HTML meta."""
    for bom, codec in _BOMS:
        if body.startswith(bom):
            return codec, "bom"
    head = body[:_SNIFF_BYTES]
    match = _XML_ENCODING_RE.search(head)
    if match is not None:
        return normalize_codec(
            match.group(1).decode("ascii", errors="replace")
        ), "xml_declaration"
    match = _META_CHARSET_RE.search(head)
    if match is not None:
        return normalize_codec(
            match.group(1).decode("ascii", errors="replace")
        ), "meta_charset"
    return None, None


def inspect_encoding(body: bytes, content_type: str | None) -> dict:
    """Full inspection dict (models.EncodingInspection wire shape).

    mojibakeRisk = declared/detected mismatch OR invalid UTF-8 sequences
    present. ``sample`` is the ≤200-char decode around the first invalid
    byte with replacement chars as the mask (None when everything round-
    tripped cleanly).
    """
    declared, declared_method = _declared_from_body(body)
    header_charset = normalize_codec(
        _HEADER_CHARSET_RE.search(content_type or "").group(1)
        if _HEADER_CHARSET_RE.search(content_type or "")
        else None
    )
    if declared is None and header_charset is not None:
        declared, declared_method = header_charset, "content_type_header"
    utf8_valid = _utf8_valid(body)
    # detected: BOM wins; else a DECLARED codec that cleanly decodes the
    # bytes — unless the codec is permissive (single-byte codecs like
    # latin-1 decode ANY bytes, so success carries no evidence); else
    # utf-8 when valid; else unknown (no guessing).
    detected: str | None = None
    detected_method: str | None = None
    for bom, codec in _BOMS:
        if body.startswith(bom):
            detected, detected_method = codec, "bom"
            break
    if detected is None:
        if (
            declared is not None
            and not _permissive_codec(declared)
            and _decodes_cleanly(body, declared)
        ):
            detected, detected_method = declared, declared_method
        elif utf8_valid:
            detected, detected_method = "utf-8", "utf8_validity"
        else:
            detected, detected_method = "unknown", "utf8_invalid"
    mismatch = (
        declared is not None
        and detected not in (None, "unknown")
        and normalize_codec(declared) != normalize_codec(detected)
    )
    # Risk = declared/detected mismatch OR the best-choice decode still
    # hits undecodable bytes (replacement chars). A healthy non-UTF-8
    # feed that cleanly decodes under its own declaration is NOT flagged.
    best_codec = detected if detected not in (None, "unknown") else declared
    sample = _masked_sample(body, codec=best_codec)
    has_bad_bytes = sample is not None or _has_replacement(body, best_codec)
    mojibake_risk = mismatch or has_bad_bytes
    return {
        "declared": declared,
        "declaredMethod": declared_method,
        "detected": detected,
        "detectedMethod": detected_method,
        "utf8Valid": utf8_valid,
        "mojibakeRisk": mojibake_risk,
        "sample": sample,
        "bodyBytes": len(body),
    }


def resolve_override_codec(
    override: str, inspection: dict
) -> str | None:
    """encoding_override choice → concrete codec (None = keep raw parse).

    - utf-8: always utf-8 (the point is to test that explicit choice);
    - declared: the document's declared codec, else utf-8 fallback;
    - detected: the heuristic result, else utf-8 fallback.
    """
    fallback = inspection.get("detected") if inspection.get("detected") not in (
        None,
        "unknown",
    ) else None
    if override == "utf-8":
        return "utf-8"
    if override == "declared":
        return normalize_codec(inspection.get("declared")) or fallback or "utf-8"
    if override == "detected":
        return fallback or "utf-8"
    return None


def decode_sample(body: bytes, codec: str | None, *, width: int = _SAMPLE_CHARS) -> str:
    """≤width-char whitespace-collapsed sample decoded under ``codec``
    (replacement chars stay in — that IS the honest masking)."""
    collapsed = " ".join(_decode_replace(body, codec).split())
    return collapsed[:width]


def _has_replacement(body: bytes, codec: str | None) -> bool:
    return "\ufffd" in _decode_replace(body, codec)


def _utf8_valid(body: bytes) -> bool:
    try:
        body.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _decodes_cleanly(body: bytes, codec: str | None) -> bool:
    if not codec:
        return False
    try:
        body.decode(codec, errors="strict")
    except (UnicodeDecodeError, LookupError):
        return False
    return True


def _permissive_codec(codec: str | None) -> bool:
    """True for codecs that decode ARBITRARY bytes (single-byte codecs like
    latin-1 / windows-1252): a clean decode under them is no evidence."""
    if not codec:
        return False
    try:
        b"\xff\xfe".decode(codec, errors="strict")
    except (UnicodeDecodeError, LookupError):
        return False
    return True


def _decode_replace(body: bytes, codec: str | None) -> str:
    """Decode with replacement (never raises, even on unknown codecs)."""
    try:
        return body.decode(codec or "utf-8", errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _masked_sample(body: bytes, codec: str | None) -> str | None:
    """Sample around the first undecodable byte, or None when clean."""
    try:
        body.decode(codec or "utf-8", errors="strict")
        return None  # everything decoded: no masking needed
    except (UnicodeDecodeError, LookupError):
        pass
    text = _decode_replace(body, codec)
    position = text.find("\ufffd")
    if position < 0:
        return None
    start = max(0, position - _SAMPLE_CHARS // 2)
    end = min(len(text), position + _SAMPLE_CHARS // 2)
    return text[start:end]
