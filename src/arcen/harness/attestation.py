"""Detached, explicitly keyed manifest attestations; never an adoption gate.

The caller supplies the trust anchor. A valid signature binds a manifest object
ID, a claimed parent ID and the signer's key fingerprint, not safety or an
independently verified lineage. The existing v1 manifest format is unchanged.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from .resolver import HarnessError
from .store import HarnessStore

MAX_ATTESTATION_BYTES = 4096
_DOMAIN = b"ARCEN-HARNESS-ATTESTATION\x00v1\x00"
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_SIGNATURE = re.compile(r"[0-9a-f]{128}\Z")
_FIELDS = frozenset(
    {"schema_version", "algorithm", "manifest", "parent", "public_key_sha256", "signature"}
)


@dataclass(frozen=True, slots=True)
class VerifiedAttestation:
    manifest: str
    parent: str | None
    public_key_sha256: str


def _crypto():
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
    except ImportError:
        raise HarnessError("attestation requires the arcen[attestation] extra") from None
    return Ed25519PrivateKey, Ed25519PublicKey, InvalidSignature


def _id(value: object) -> bool:
    return type(value) is str and bool(_HASH.fullmatch(value))


def _canonical(doc: dict) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _payload(doc: dict) -> bytes:
    return _DOMAIN + _canonical({key: value for key, value in doc.items() if key != "signature"})


def create_attestation(manifest: str, parent: str | None, private_key: object) -> bytes:
    """Sign claims with a caller-owned Ed25519 key; performs no store checks.

    Private-key creation, custody, authorization and persistence are outside
    this API. The resulting bytes can be verified offline against an explicitly
    supplied public key. Signing does not select or adopt a harness.
    """
    private_type, _, _ = _crypto()
    if not _id(manifest) or (parent is not None and not _id(parent)) or parent == manifest:
        raise HarnessError("invalid attestation manifest or parent")
    if not isinstance(private_key, private_type):
        raise HarnessError("attestation requires an Ed25519 private key")
    key_bytes = private_key.public_key().public_bytes_raw()
    doc = {
        "schema_version": 1,
        "algorithm": "ed25519",
        "manifest": manifest,
        "parent": parent,
        "public_key_sha256": hashlib.sha256(key_bytes).hexdigest(),
    }
    doc["signature"] = private_key.sign(_payload(doc)).hex()
    return _canonical(doc)


def _parse(data: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise HarnessError("invalid attestation")
            result[key] = value
        return result

    if type(data) is not bytes or len(data) > MAX_ATTESTATION_BYTES:
        raise HarnessError("invalid attestation")
    try:
        doc = json.loads(data.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise HarnessError("invalid attestation") from None
    if type(doc) is not dict or set(doc) != _FIELDS:
        raise HarnessError("invalid attestation")
    if (
        type(doc["schema_version"]) is not int
        or doc["schema_version"] != 1
        or doc["algorithm"] != "ed25519"
        or not _id(doc["manifest"])
        or (doc["parent"] is not None and not _id(doc["parent"]))
        or doc["parent"] == doc["manifest"]
        or not _id(doc["public_key_sha256"])
        or type(doc["signature"]) is not str
        or not _SIGNATURE.fullmatch(doc["signature"])
    ):
        raise HarnessError("invalid attestation")
    if _canonical(doc) != data:
        raise HarnessError("noncanonical attestation")
    return doc


def verify_attestation(
    store: HarnessStore, manifest: str, data: bytes, public_key: bytes
) -> VerifiedAttestation:
    """Verify a signature and every object against an independently supplied key.

    Returns a signed parent *claim*; it is not a verified lineage edge. The
    caller must authenticate the public key separately and establish all other
    authorization and safety gates independently.
    """
    if not _id(manifest) or type(public_key) is not bytes or len(public_key) != 32:
        raise HarnessError("invalid manifest ID or public key")
    _, public_type, invalid_signature = _crypto()
    doc = _parse(data)
    fingerprint = hashlib.sha256(public_key).hexdigest()
    if doc["manifest"] != manifest or doc["public_key_sha256"] != fingerprint:
        raise HarnessError("attestation does not match requested manifest or public key")
    try:
        public_type.from_public_bytes(public_key).verify(
            bytes.fromhex(doc["signature"]), _payload(doc)
        )
    except (invalid_signature, ValueError):
        raise HarnessError("attestation signature verification failed") from None
    # Verify canonical manifest and every referenced blob before reporting OK.
    store.get_manifest(manifest)
    return VerifiedAttestation(manifest, doc["parent"], fingerprint)
