"""ItemRef parser/serializer tests (phase2 M1).

The typed ref is the backbone of every cross-domain relation; these
tests pin the two legal shapes and the rejection of everything else
(wrong prefix, non-canonical uuid, non-entryRef rss payload, size).
"""

import pytest

from lumirss.entryref import encode_entry_ref
from lumirss.itemref import (
    InvalidItemRef,
    library_item_ref,
    parse_item_ref,
    rss_item_ref,
)


def test_valid_rss_ref_round_trips():
    ref = "rss:" + encode_entry_ref("1001")
    parsed = parse_item_ref(ref)
    assert parsed.domain == "rss"
    assert parsed.format() == ref


def test_valid_library_ref_round_trips():
    ref = "library:0b8df3e0-1f2a-4c3d-9e4f-5a6b7c8d9e0f"
    parsed = parse_item_ref(ref)
    assert parsed.domain == "library"
    assert parsed.format() == ref


def test_rejects_missing_or_wrong_prefix():
    for bad in ["", "rss", "library:", "e1.abc", "fresh:e1.abc", "rss2:e1.abc"]:
        with pytest.raises(InvalidItemRef):
            parse_item_ref(bad)


def test_rejects_non_entryref_rss_payload():
    with pytest.raises(InvalidItemRef):
        parse_item_ref("rss:not-an-entryref")


def test_rejects_non_canonical_uuid():
    # Uppercase uuids parse as valid UUID but are not canonical form.
    with pytest.raises(InvalidItemRef):
        parse_item_ref("library:0B8DF3E0-1F2A-4C3D-9E4F-5A6B7C8D9E0F")
    with pytest.raises(InvalidItemRef):
        parse_item_ref("library:not-a-uuid")


def test_rejects_oversized_ref():
    with pytest.raises(InvalidItemRef):
        parse_item_ref("rss:" + "A" * 600)


def test_helper_builders_validate():
    entry = encode_entry_ref("7")
    assert rss_item_ref(entry) == "rss:" + entry
    assert library_item_ref(
        "0b8df3e0-1f2a-4c3d-9e4f-5a6b7c8d9e0f"
    ).startswith("library:")
    with pytest.raises(InvalidItemRef):
        rss_item_ref("bogus")
