"""subscriptionRef — LumiRSS's opaque, URL-safe reference to a FreshRSS
subscription (0013 management contract).

Format: ``s1.`` + base64url(utf-8 upstream stream id, e.g. ``feed/52``)
without ``=`` padding — same packaging rules as entryRef.

Encoding is NOT encryption, and a subscriptionRef is not authorization: it
is a reversible, deterministic packaging of the FreshRSS ``feed/NN`` stream
id so that Lumi URLs never depend on clients understanding or assembling
Google Reader id shapes. Clients must treat subscriptionRef as an opaque
string. Only refs whose decoded payload is a well-formed ``feed/<id>``
(positive integer) are accepted; anything else is a malformed reference.
"""

import base64

_REF_PREFIX = "s1."
_MAX_REF_LENGTH = 512
_BASE64URL_ALPHABET = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)


class InvalidSubscriptionReference(ValueError):
    """subscriptionRef has a wrong prefix, invalid characters, bad UTF-8,
    bad size, or does not decode to a well-formed feed/<id> stream id."""


def encode_subscription_ref(stream_id: str) -> str:
    """Package an upstream FreshRSS stream id (``feed/NN``) into an opaque
    subscriptionRef."""
    if not stream_id:
        raise ValueError("upstream stream id must not be empty.")
    payload = base64.urlsafe_b64encode(stream_id.encode("utf-8"))
    return _REF_PREFIX + payload.decode("ascii").rstrip("=")


def decode_subscription_ref(subscription_ref: str) -> str:
    """Reverse of encode_subscription_ref; raises
    InvalidSubscriptionReference on bad input."""
    if len(subscription_ref) > _MAX_REF_LENGTH:
        raise InvalidSubscriptionReference("subscriptionRef is too long.")
    if not subscription_ref.startswith(_REF_PREFIX):
        raise InvalidSubscriptionReference("subscriptionRef must start with 's1.'.")
    payload = subscription_ref[len(_REF_PREFIX):]
    if not payload or not _BASE64URL_ALPHABET.issuperset(payload):
        raise InvalidSubscriptionReference("subscriptionRef payload is not valid base64url.")
    padded = payload + "=" * (-len(payload) % 4)
    try:
        stream_id = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidSubscriptionReference(
            "subscriptionRef payload is not valid UTF-8."
        ) from exc
    # Only stream ids we could have produced are accepted (feed/<positive int>).
    body = stream_id.removeprefix("feed/")
    if (
        not stream_id.startswith("feed/")
        or not body.isdigit()
        or body.startswith("0")
        or len(body) > 10
    ):
        raise InvalidSubscriptionReference(
            "subscriptionRef payload is not a well-formed feed id."
        )
    return stream_id
