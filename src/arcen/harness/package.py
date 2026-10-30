"""Portable signed v1 harness packages; importing never activates or adopts.

Packages contain a canonical manifest, detached attestation and exact blobs.
Verification is in memory; optional import stores content-addressed objects
without changing refs. Callers must supply an independently authenticated key.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .attestation import MAX_ATTESTATION_BYTES, VerifiedAttestation, verify_attestation
from .manifest import COMPONENT_PATHS, MAX_COMPONENT_BYTES, Manifest
from .model import canonical_manifest, content_hash, parse_manifest
from .resolver import HarnessError
from .store import HarnessStore

MAX_PACKAGE_BYTES = 10 * 1024 * 1024
_FIELDS = frozenset({"schema_version", "manifest", "attestation", "objects"})


@dataclass(frozen=True, slots=True)
class VerifiedPackage:
    attestation: VerifiedAttestation
    component_count: int
    unique_objects: int


def _encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _decode(value: object, limit: int) -> bytes:
    if type(value) is not str or len(value) > 4 * ((limit + 2) // 3):
        raise HarnessError("invalid package data")
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise HarnessError("invalid package data") from None
    if len(raw) > limit or _encode(raw) != value:
        raise HarnessError("invalid package data")
    return raw


def _canonical(doc: dict) -> bytes:
    try:
        return json.dumps(
            doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("ascii")
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise HarnessError("invalid package data") from None


class _MemoryStore:
    """Read-only store facade for the existing signature verifier."""

    def __init__(self, raw_manifest: bytes, objects: dict[str, bytes]):
        self.raw_manifest = raw_manifest
        self.objects = objects

    def get_manifest(self, digest: str) -> Manifest:
        if content_hash(self.raw_manifest) != digest:
            raise HarnessError("package manifest hash mismatch")
        manifest = parse_manifest(self.raw_manifest)
        if canonical_manifest(manifest) != self.raw_manifest:
            raise HarnessError("package manifest is not canonical")
        if set(self.objects) != set(manifest.components.values()):
            raise HarnessError("package component set mismatch")
        if any(content_hash(blob) != key for key, blob in self.objects.items()):
            raise HarnessError("package component hash mismatch")
        return manifest


def _verified_contents(
    data: bytes, expected_manifest: str, public_key: bytes
) -> tuple[VerifiedPackage, Manifest, dict[str, bytes]]:
    """Verify and retain the same immutable bytes for a possible import."""
    if type(data) is not bytes or not data or len(data) > MAX_PACKAGE_BYTES:
        raise HarnessError("invalid or oversized package")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise HarnessError("duplicate package key")
            result[key] = value
        return result

    try:
        doc = json.loads(data.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeError, ValueError, RecursionError):
        raise HarnessError("invalid package") from None
    if (
        type(doc) is not dict
        or set(doc) != _FIELDS
        or type(doc["schema_version"]) is not int
        or doc["schema_version"] != 1
        or type(doc["objects"]) is not dict
        or len(doc["objects"]) > len(COMPONENT_PATHS)
    ):
        raise HarnessError("invalid package fields")
    if _canonical(doc) != data:
        raise HarnessError("noncanonical package")
    raw_manifest = _decode(doc["manifest"], MAX_COMPONENT_BYTES)
    signature = _decode(doc["attestation"], MAX_ATTESTATION_BYTES)
    objects = {key: _decode(value, MAX_COMPONENT_BYTES) for key, value in doc["objects"].items()}
    store = _MemoryStore(raw_manifest, objects)
    # The signed expected ID and explicit key are checked before the contents.
    attestation = verify_attestation(store, expected_manifest, signature, public_key)
    manifest = store.get_manifest(expected_manifest)
    return VerifiedPackage(attestation, len(manifest.components), len(objects)), manifest, objects


def verify_package(data: bytes, expected_manifest: str, public_key: bytes) -> VerifiedPackage:
    """Verify an untrusted package without extraction, activation or writes."""
    result, _, _ = _verified_contents(data, expected_manifest, public_key)
    return result


def import_package(
    store: HarnessStore, data: bytes, expected_manifest: str, public_key: bytes
) -> VerifiedPackage:
    """Store verified objects only; never register lineage, change refs or run.

    Verification and preflight precede writes. Publishing uses the existing
    atomic per-object store API; a later failure can leave unreferenced objects.
    The store and local filesystem writers must be trusted.
    """
    result, manifest, objects = _verified_contents(data, expected_manifest, public_key)
    # Refuse corrupt pre-existing objects before inserting anything. This is
    # not a lock against concurrent/hostile filesystem changes.
    for digest in sorted({*objects, expected_manifest}):
        path = store._path(digest)
        if path.exists() or path.is_symlink():
            store.get_blob(digest)
    for digest, blob in sorted(objects.items()):
        if store.put_blob(blob) != digest:
            raise HarnessError("imported object hash mismatch")
    if store.put_manifest(manifest) != expected_manifest:
        raise HarnessError("imported manifest hash mismatch")
    store.get_manifest(expected_manifest)
    return result


def export_package(
    store: HarnessStore, manifest_id: str, attestation: bytes, public_key: bytes
) -> bytes:
    """Build an inspection-only package from verified content and a signature."""
    verify_attestation(store, manifest_id, attestation, public_key)
    manifest = store.get_manifest(manifest_id)
    manifest_bytes = store.get_blob(manifest_id)
    objects = {digest: _encode(store.get_blob(digest)) for digest in manifest.components.values()}
    data = _canonical(
        {
            "schema_version": 1,
            "manifest": _encode(manifest_bytes),
            "attestation": _encode(attestation),
            "objects": objects,
        }
    )
    if len(data) > MAX_PACKAGE_BYTES:
        raise HarnessError("package exceeds size limit")
    verify_package(data, manifest_id, public_key)
    return data


def write_new_package(path: str, data: bytes) -> None:
    """Atomically publish a mode-0600 package, never replacing an existing path.

    Parent directory and concurrent local filesystem writers must be trusted.
    This does not guarantee directory durability across a crash.
    """
    if (
        type(path) is not str
        or not path
        or type(data) is not bytes
        or len(data) > MAX_PACKAGE_BYTES
    ):
        raise HarnessError("invalid package output")
    destination = Path(path).expanduser()
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".arcen-package-", dir=destination.parent, delete=False
        ) as stream:
            tmp_name = stream.name
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(tmp_name, destination, follow_symlinks=False)
    except FileExistsError:
        raise HarnessError("package output already exists") from None
    except OSError:
        raise HarnessError("cannot write package output") from None
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
