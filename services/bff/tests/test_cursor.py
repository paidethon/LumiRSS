"""Test G — cursor encode/decode round-trip and every invalid branch.

Pure functions, no network. Every fake value here is clearly test data.
"""

import base64
import json

import pytest

from lumirss.cursor import (
    CursorScope,
    InvalidCursor,
    decode_cursor,
    encode_cursor,
)


def test_round_trip_with_feed_url():
    cursor = encode_cursor("12345", "unread", "https://example.com/feed.xml")
    scope = decode_cursor(cursor)
    assert scope == CursorScope(
        continuation="12345", view="unread", feed_url="https://example.com/feed.xml"
    )


def test_round_trip_without_feed_url():
    cursor = encode_cursor("999", "all", None)
    scope = decode_cursor(cursor)
    assert scope == CursorScope(continuation="999", view="all", feed_url=None)


def test_cursor_is_deterministic_and_url_safe():
    a = encode_cursor("12345", "starred", None)
    b = encode_cursor("12345", "starred", None)
    assert a == b
    assert a.startswith("c1.")
    payload = a[len("c1."):]
    assert "=" not in payload
    assert all(c.isalnum() or c in "-_" for c in payload)


def test_payload_is_compact_json_with_expected_fields():
    cursor = encode_cursor("12345", "unread", "https://example.com/feed.xml")
    raw = cursor[len("c1."):]
    padded = raw + "=" * (-len(raw) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    assert payload == {"c": "12345", "v": "unread", "f": "https://example.com/feed.xml"}


def test_encode_rejects_empty_continuation_and_bad_view():
    with pytest.raises(ValueError):
        encode_cursor("", "all", None)
    with pytest.raises(ValueError):
        encode_cursor("123", "bogus", None)


def test_encode_rejects_non_digit_continuation():
    with pytest.raises(ValueError):
        encode_cursor("not-digits", "all", None)


# --- invalid cursors → InvalidCursor ---------------------------------------


def make_cursor(payload_obj, prefix="c1.") -> str:
    body = json.dumps(payload_obj, separators=(",", ":"), ensure_ascii=False)
    encoded = base64.urlsafe_b64encode(body.encode("utf-8")).decode("ascii").rstrip("=")
    return prefix + encoded


VALID = {"c": "12345", "v": "unread", "f": None}


def test_bad_prefix_is_rejected():
    with pytest.raises(InvalidCursor):
        decode_cursor("e1." + make_cursor(VALID)[len("c1."):])
    with pytest.raises(InvalidCursor):
        decode_cursor(make_cursor(VALID, prefix="c2."))


def test_empty_payload_is_rejected():
    with pytest.raises(InvalidCursor):
        decode_cursor("c1.")


def test_bad_base64url_characters_are_rejected():
    with pytest.raises(InvalidCursor):
        decode_cursor("c1.a+/=")  # standard base64 chars are not allowed


def test_invalid_utf8_is_rejected():
    bad = base64.urlsafe_b64encode(b"\xff\xfe").decode("ascii").rstrip("=")
    with pytest.raises(InvalidCursor):
        decode_cursor("c1." + bad)


def test_bad_json_is_rejected():
    not_json = base64.urlsafe_b64encode(b"not json").decode("ascii").rstrip("=")
    with pytest.raises(InvalidCursor):
        decode_cursor("c1." + not_json)


def test_wrong_schema_is_rejected():
    with pytest.raises(InvalidCursor):  # missing 'f'
        decode_cursor(make_cursor({"c": "1", "v": "all"}))
    with pytest.raises(InvalidCursor):  # extra key
        decode_cursor(make_cursor({"c": "1", "v": "all", "f": None, "x": 1}))
    with pytest.raises(InvalidCursor):  # not an object
        decode_cursor(make_cursor(["c", "v", "f"]))


def test_invalid_continuation_is_rejected():
    with pytest.raises(InvalidCursor):  # non-digit
        decode_cursor(make_cursor({"c": "12a45", "v": "all", "f": None}))
    with pytest.raises(InvalidCursor):  # empty
        decode_cursor(make_cursor({"c": "", "v": "all", "f": None}))
    with pytest.raises(InvalidCursor):  # not a string
        decode_cursor(make_cursor({"c": 12345, "v": "all", "f": None}))


def test_invalid_view_is_rejected():
    with pytest.raises(InvalidCursor):
        decode_cursor(make_cursor({"c": "1", "v": "bogus", "f": None}))


def test_invalid_feed_url_type_is_rejected():
    with pytest.raises(InvalidCursor):  # number is neither str nor null
        decode_cursor(make_cursor({"c": "1", "v": "all", "f": 42}))


def test_too_long_cursor_is_rejected():
    with pytest.raises(InvalidCursor):
        decode_cursor("c1." + "a" * 3000)
