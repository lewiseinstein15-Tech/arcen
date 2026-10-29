"""Resolve only the packaged adopted baseline for headless execution.

Candidate execution remains unavailable until the isolated probe, approval and
adoption gates exist. The local store is a trusted filesystem, not a signature.
"""

from __future__ import annotations

from .cli import _existing
from .manifest import default_manifest
from .model import canonical_manifest, content_hash
from .resolver import HarnessError

_ADOPTED = "refs/heads/adopted"


def resolve_packaged_baseline(ref: str, store_root: str = "~/.arcen/harness") -> str:
    """Resolve a verified adopted ref only when it is the bundled baseline.

    Return its content-addressed ID. No candidate, unrecognized ref, missing
    store or changed adopted metadata silently falls back to bundled prompts.
    """
    if type(store_root) is not str or not store_root.strip():
        raise HarnessError("invalid harness store path")
    if ref not in ("adopted", _ADOPTED):
        raise HarnessError("candidate selection unavailable; no harness reference was applied")
    store, lineage = _existing(store_root)
    selected = lineage.resolve(_ADOPTED)
    expected = content_hash(canonical_manifest(default_manifest()))
    if selected != expected or store.get_manifest(selected) != default_manifest():
        raise HarnessError("adopted ref is not the packaged baseline")
    return selected
