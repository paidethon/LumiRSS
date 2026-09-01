"""subscriptionRef packaging tests (0013 Gate 1).

Same opaque-reference rules as entryRef, plus one extra: the decoded payload
must be a well-formed ``feed/<positive int>`` stream id (the only shape this
module ever produces).
"""

import base64

import pytest

from lumirss.subscriptionref import (
    InvalidSubscriptionReference,
    decode_subscription_ref,
    encode_subscription_ref,
)


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def test_roundtrip_of_upstream_stream_id():
    ref = encode_subscription_ref("feed/52")
    assert ref.startswith("s1.")
    assert decode_subscription_ref(ref) == "feed/52"


def test_encode_rejects_empty_stream_id():
    with pytest.raises(ValueError):
        encode_subscription_ref("")


@pytest.mark.parametrize(
    "bad_ref",
    [
        "",
        "feed/52",  # no prefix
        "e1.ZmVlZC81Mg",  # entryRef prefix, not subscriptionRef
        "s1.",  # empty payload
        "s1.???!",  # not base64url
        "s1." + b64url(b"hello"),  # decodes, but not a feed id
        "s1." + b64url(b"feed/abc"),  # non-numeric feed id
        "s1." + b64url(b"feed/"),  # empty id
        "s1." + b64url(b"feed/0"),  # zero is not a valid id
        "s1." + b64url(b"feed/007"),  # leading zero: not a shape we produce
        "s1." + b64url(b"feed/" + b"1" * 11),  # implausibly large id
        "s1." + b64url(b"\xff\xfe"),  # not valid UTF-8
        "s1." + "A" * 600,  # too long
    ],
)
def test_malformed_refs_are_rejected(bad_ref):
    with pytest.raises(InvalidSubscriptionReference):
        decode_subscription_ref(bad_ref)


def test_invalid_reference_is_a_value_error():
    assert issubclass(InvalidSubscriptionReference, ValueError)
