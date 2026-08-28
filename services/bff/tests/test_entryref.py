"""Test C — entryRef round-trip and rejection of invalid references.

Pure-function tests: no network, no FreshRSS, no secrets.
"""

import base64

import pytest

from lumirss.entryref import (
    InvalidEntryReference,
    decode_entry_ref,
    encode_entry_ref,
)

UPSTREAM_ID = "tag:google.com,2005:reader/item/000659e07aaee24d"


def test_round_trip_restores_upstream_id():
    ref = encode_entry_ref(UPSTREAM_ID)

    assert ref.startswith("e1.")
    assert decode_entry_ref(ref) == UPSTREAM_ID


def test_ref_is_url_safe_and_unpadded():
    ref = encode_entry_ref(UPSTREAM_ID)

    assert not {"=", "/", "+", ":", ","} & set(ref)


def test_encoding_is_deterministic():
    assert encode_entry_ref(UPSTREAM_ID) == encode_entry_ref(UPSTREAM_ID)


def test_unicode_upstream_id_round_trip():
    upstream = "tag:example.com,2005:条目/中文"

    assert decode_entry_ref(encode_entry_ref(upstream)) == upstream


@pytest.mark.parametrize(
    "bad_ref",
    [
        "e2.dGFn",  # wrong version prefix
        "x1.dGFn",  # unknown prefix
        "dGFn",  # no prefix at all
        "e1.",  # empty payload
        "e1.AB+CD",  # '+' is not base64url
        "e1.AB/CD",  # '/' is not base64url
        "e1.AB=CD",  # padding '=' is not allowed
        "e1.A",  # impossible base64url length (1 mod 4)
        "e1." + "A" * 600,  # obviously oversized
    ],
)
def test_invalid_references_are_rejected(bad_ref):
    with pytest.raises(InvalidEntryReference):
        decode_entry_ref(bad_ref)


def test_non_utf8_payload_is_rejected():
    payload = base64.urlsafe_b64encode(b"\xff\xfe").decode("ascii").rstrip("=")

    with pytest.raises(InvalidEntryReference):
        decode_entry_ref("e1." + payload)


def test_encode_rejects_empty_item_id():
    with pytest.raises(ValueError):
        encode_entry_ref("")
