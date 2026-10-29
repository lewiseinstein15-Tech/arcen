"""Canonical immutable content identities for the harness store."""

from __future__ import annotations

import hashlib
import json
import re
from types import MappingProxyType

from .manifest import COMPONENT_PATHS, Manifest
from .resolver import HarnessError

_HASH = re.compile(r"[0-9a-f]{64}\Z")
_PIN = re.compile(r"fixed:[a-z][a-z0-9_-]{0,31}:[^\s]{1,200}\Z")


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_manifest(manifest: Manifest) -> bytes:
    """Deterministic UTF-8 encoding; equivalent maps have identical hashes."""
    doc = {
        "schema_version": manifest.schema_version,
        "model_pin": manifest.model_pin,
        "components": dict(manifest.components),
    }
    # Round trip through strict validation before persisting.
    encoded = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    parse_manifest(encoded)
    return encoded


def parse_manifest(data: bytes) -> Manifest:
    """Parse a strict canonical representation; duplicate keys are forbidden."""

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise HarnessError("duplicate manifest key")
            result[key] = value
        return result

    try:
        doc = json.loads(data.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise HarnessError("invalid stored manifest") from exc
    if type(doc) is not dict or set(doc) != {"schema_version", "model_pin", "components"}:
        raise HarnessError("invalid stored manifest fields")
    if type(doc["schema_version"]) is not int or doc["schema_version"] != 1:
        raise HarnessError("unsupported stored manifest schema")
    pin = doc["model_pin"]
    if type(pin) is not str or not (pin == "provider-configured" or _PIN.fullmatch(pin)):
        raise HarnessError("invalid stored model pin")
    components = doc["components"]
    if type(components) is not dict or set(components) != COMPONENT_PATHS:
        raise HarnessError("invalid stored component set")
    if any(type(value) is not str or not _HASH.fullmatch(value) for value in components.values()):
        raise HarnessError("invalid stored component hash")
    return Manifest(1, pin, MappingProxyType(dict(components)))
