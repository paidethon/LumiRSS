"""subscriptionRef — LumiRSS's opaque, URL-safe reference to a FreshRSS
subscription (0013 management contract).

Format: ``s1.`` + base64url(utf-8 upstream stream id, e.g. ``feed/52``)
without ``=`` padding — the shared envelope lives in
:mod:`lumirss.opaque_ref`.

Encoding is NOT encryption, and a subscriptionRef is not authorization: it
is a reversible, deterministic packaging of the FreshRSS ``feed/NN`` stream
id so that Lumi URLs never depend on clients understanding or assembling
Google Reader id shapes. Clients must treat subscriptionRef as an opaque
string. Only refs whose decoded payload is a well-formed ``feed/<id>``
(positive integer) are accepted; anything else is a malformed reference.
"""

from lumirss.opaque_ref import decode_opaque_ref, encode_opaque_ref

_REF_PREFIX = "s1."
_MAX_REF_LENGTH = 512


class InvalidSubscriptionReference(ValueError):
    """subscriptionRef has a wrong prefix, invalid characters, bad UTF-8,
    bad size, or does not decode to a well-formed feed/<id> stream id."""


def encode_subscription_ref(stream_id: str) -> str:
    """Package an upstream FreshRSS stream id (``feed/NN``) into an opaque
    subscriptionRef."""
    if not stream_id:
        raise ValueError("upstream stream id must not be empty.")
    return encode_opaque_ref(_REF_PREFIX, stream_id)


def is_well_formed_feed_stream_id(stream_id: str) -> bool:
    """Whether ``stream_id`` matches the feed/<positive int> rule that
    Lumi itself produces (single shared rule for ref decode and the
    control-plane adapter)."""
    body = stream_id.removeprefix("feed/")
    return (
        stream_id.startswith("feed/")
        and body.isdigit()
        and not body.startswith("0")
        and len(body) <= 10
    )


def decode_subscription_ref(subscription_ref: str) -> str:
    """Reverse of encode_subscription_ref; raises
    InvalidSubscriptionReference on bad input."""
    stream_id = decode_opaque_ref(
        subscription_ref,
        prefix=_REF_PREFIX,
        max_length=_MAX_REF_LENGTH,
        error_type=InvalidSubscriptionReference,
        description="subscriptionRef",
    )
    # Only stream ids we could have produced are accepted (feed/<positive int>).
    if not is_well_formed_feed_stream_id(stream_id):
        raise InvalidSubscriptionReference(
            "subscriptionRef payload is not a well-formed feed id."
        )
    return stream_id
