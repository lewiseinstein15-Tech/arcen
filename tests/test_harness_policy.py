"""Double-layer protected component and fail-closed adoption checks."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest

from arcen.harness import HarnessError
from arcen.harness.editor import apply_exact_diff
from arcen.harness.manifest import Manifest, default_manifest
from arcen.harness.policy import AdoptionUnavailable, adopt_candidate, review_candidate
from arcen.harness.store import HarnessStore

ROOT = Path(__file__).resolve().parents[1] / "src/arcen"


def setup_store(tmp_path):
    store = HarnessStore(tmp_path / "store")
    manifest = default_manifest()
    for path in manifest.components:
        store.put_blob((ROOT / path).read_bytes())
    baseline = store.put_manifest(manifest)
    return store, manifest, baseline


def candidate(store, base, changes, pin=None):
    components = dict(base.components)
    for path, content in changes.items():
        components[path] = store.put_blob(content)
    return store.put_manifest(Manifest(1, pin or base.model_pin, MappingProxyType(components)))


@pytest.mark.parametrize("path", ["guardrails/policy.yaml", "tools/registry.toml"])
def test_protected_edits_fail_at_editor_and_review_layers(tmp_path, path):
    store, base, baseline = setup_store(tmp_path)
    edited = candidate(store, base, {path: b"unsafe\n"})
    with pytest.raises(HarnessError, match="not editable"):
        apply_exact_diff(store.get_blob(base.components[path]), path, "bad")
    with pytest.raises(HarnessError, match="protected candidate"):
        review_candidate(store, baseline, edited)
    with pytest.raises(HarnessError, match="protected baseline"):
        review_candidate(store, edited, edited)
    with pytest.raises(AdoptionUnavailable):
        adopt_candidate(store, baseline, edited)


def test_tiers_are_review_only_and_no_adoption(tmp_path):
    store, base, baseline = setup_store(tmp_path)
    guidance = store.get_blob(base.components["tool-guidance.md"]) + b"additional guidance\n"
    forge = store.get_blob(base.components["prompts/forge.md"]) + b"extra guidance\n"
    tier2 = candidate(store, base, {"tool-guidance.md": guidance})
    mixed = candidate(store, base, {"tool-guidance.md": guidance, "prompts/forge.md": forge})
    review2 = review_candidate(store, baseline, tier2)
    assert (
        review2.highest_tier == 2
        and review2.human_review_required
        and not review2.adoption_available
    )
    review1 = review_candidate(store, baseline, mixed)
    assert review1.highest_tier == 1 and len(review1.changed_paths) == 2
    with pytest.raises(AdoptionUnavailable):
        adopt_candidate(store, baseline, tier2)
    with pytest.raises(AdoptionUnavailable):
        adopt_candidate(store, baseline, mixed)


def test_invalid_model_prompt_and_unchanged_rejected(tmp_path):
    store, base, baseline = setup_store(tmp_path)
    with pytest.raises(HarnessError, match="no component changes"):
        review_candidate(store, baseline, baseline)
    bad_pin = candidate(
        store, base, {"prompts/forge.md": b"## job\nvalid\n"}, pin="fixed:custom:another"
    )
    with pytest.raises(HarnessError, match="model pin"):
        review_candidate(store, baseline, bad_pin)
    bad_prompt = candidate(store, base, {"prompts/forge.md": b"## bad\ninvalid\n"})
    with pytest.raises(HarnessError):
        review_candidate(store, baseline, bad_prompt)


def test_corrupt_candidate_object_fails_closed(tmp_path):
    store, base, baseline = setup_store(tmp_path)
    modified = candidate(store, base, {"prompts/forge.md": b"## job\nnew job\n"})
    manifest = store.get_manifest(modified)
    (store.objects / manifest.components["prompts/forge.md"]).write_bytes(b"tampered")
    with pytest.raises(HarnessError, match="integrity"):
        review_candidate(store, baseline, modified)
