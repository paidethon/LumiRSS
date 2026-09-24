"""Minimal software WebAuthn authenticator for tests (N006/N007).

Produces REAL WebAuthn structures — ES256 (SECP256R1) keypair, real
CBOR attestation objects ("none" format, matching the self-hosted RP's
documented attestation policy), real signatures over
authenticatorData || SHA256(clientDataJSON), and a monotonic sign
counter — so the server's python-fido2 verification path (RP ID hash,
origin, challenge binding, user presence, signature, clone detection)
is genuinely exercised, not mocked away. cryptography comes in
transitively via python-fido2.
"""

import hashlib
import json
import os
import struct
from datetime import UTC, datetime

import fido2.cbor as cbor
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fido2.cose import ES256
from fido2.utils import websafe_encode
from fido2.webauthn import AttestedCredentialData, AuthenticatorData

UP_UV_AT_FLAGS = 0x45  # UP | UV | AT (registration)
UP_UV_FLAGS = 0x05  # UP | UV (assertion)


class VirtualAuthenticator:
    """One credential bound to (origin, rp_id); signs real assertions."""

    def __init__(
        self,
        *,
        origin: str,
        rp_id: str,
        user_handle: bytes = b"owner",
        credential_id: bytes | None = None,
    ) -> None:
        self.origin = origin
        self.rp_id = rp_id
        self.user_handle = user_handle
        self.credential_id = credential_id or os.urandom(32)
        self._key = ec.generate_private_key(ec.SECP256R1())
        self._cose = ES256.from_cryptography_key(self._key.public_key())
        self.counter = 0

    # -- helpers ------------------------------------------------------------

    def _client_data(self, typ: str, challenge: str, origin: str | None = None) -> bytes:
        return json.dumps(
            {
                "type": typ,
                "challenge": challenge,
                "origin": origin or self.origin,
                "crossOrigin": False,
            }
        ).encode("utf-8")

    def _rp_id_hash(self) -> bytes:
        return hashlib.sha256(self.rp_id.encode("utf-8")).digest()

    # -- ceremonies -----------------------------------------------------------

    def make_registration(self, challenge: str) -> dict[str, object]:
        """RegistrationResponse JSON (browser shape) for a create ceremony."""
        client_data = self._client_data("webauthn.create", challenge)
        attested = AttestedCredentialData.create(
            bytes(16), self.credential_id, self._cose
        )
        auth_data = (
            self._rp_id_hash()
            + bytes([UP_UV_AT_FLAGS])
            + struct.pack(">I", self.counter)
            + attested
        )
        attestation = cbor.encode(
            {"fmt": "none", "attStmt": {}, "authData": AuthenticatorData(auth_data)}
        )
        return {
            "id": websafe_encode(self.credential_id),
            "rawId": websafe_encode(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": websafe_encode(client_data),
                "attestationObject": websafe_encode(bytes(attestation)),
                "transports": ["internal"],
            },
        }

    def make_assertion(
        self,
        challenge: str,
        *,
        origin: str | None = None,
        counter: int | None = None,
        corrupt_signature: bool = False,
        client_data_type: str = "webauthn.get",
    ) -> dict[str, object]:
        """AuthenticationResponse JSON for a get ceremony.

        ``counter`` overrides the monotonic counter (clone simulation);
        ``origin`` overrides the origin (wrong-site simulation);
        ``corrupt_signature`` flips the last signature byte.
        """
        self.counter = self.counter + 1 if counter is None else self.counter
        # An EXPLICIT counter does not advance the device (clone simulation:
        # the copied credential's counter is stale; the genuine device's
        # keeps its own monotonic sequence).
        used_counter = self.counter if counter is None else counter
        client_data = self._client_data(client_data_type, challenge, origin)
        auth_data = (
            self._rp_id_hash()
            + bytes([UP_UV_FLAGS])
            + struct.pack(">I", used_counter)
        )
        signature = self._key.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        if corrupt_signature:
            signature = signature[:-1] + bytes([signature[-1] ^ 0x01])
        return {
            "id": websafe_encode(self.credential_id),
            "rawId": websafe_encode(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": websafe_encode(client_data),
                "authenticatorData": websafe_encode(auth_data),
                "signature": websafe_encode(signature),
                "userHandle": websafe_encode(self.user_handle),
            },
        }


def totp_at(secret: str, epoch: int) -> str:
    """Valid 6-digit TOTP code at a fixed epoch (pyotp, RFC 6238)."""
    import pyotp

    return pyotp.TOTP(secret).at(datetime.fromtimestamp(epoch, tz=UTC))
