"""Offline H-12 composition, conflicts, integrity and no-adoption tests."""

from __future__ import annotations

import difflib
from dataclasses import replace
from types import MappingProxyType

import pytest
from test_harness_editor import setup_store

from arcen.harness.composer import compose_proposals
from arcen.harness.editor import Proposal
from arcen.harness.manifest import Manifest
from arcen.harness.model import content_hash
from arcen.harness.policy import AdoptionUnavailable, adopt_candidate, review_candidate
from arcen.harness.resolver import HarnessError


def proposal(store, baseline, path, after, *, scope="invariant"):
    original = store.get_blob(store.get_manifest(baseline).components[path])
    diff = "".join(
        difflib.unified_diff(
            original.decode().splitlines(True),
            after.decode().splitlines(True),
            fromfile="a/" + path,
            tofile="b/" + path,
        )
    )
    return Proposal(scope, path, diff, content_hash(original), after)


def test_compose_independent_files_to_content_addressed_manifest_without_adoption(tmp_path):
    store, base_id = setup_store(tmp_path)
    base = store.get_manifest(base_id)
    paths = ("prompts/forge.md", "prompts/temper.md")
    p = tuple(
        proposal(store, base_id, path, store.get_blob(base.components[path]) + b"Be careful.\n")
        for path in paths
    )
    result = compose_proposals(store, base_id, p)
    assert result.candidate_id and result.conflicts == ()
    assert result.changed_paths == tuple(sorted(paths))
    result_manifest = store.get_manifest(result.candidate_id)
    assert result_manifest.model_pin == base.model_pin
    assert all(store.get_blob(result_manifest.components[x.path]) == x.after for x in p)
    assert review_candidate(store, base_id, result.candidate_id).human_review_required
    with pytest.raises(AdoptionUnavailable):
        adopt_candidate(store, base_id, result.candidate_id)
    assert compose_proposals(store, base_id, tuple(reversed(p))).candidate_id == result.candidate_id


def test_separated_edits_same_file_merge_and_duplicate_edits_deduplicate(tmp_path):
    store, base_id = setup_store(tmp_path)
    base = store.get_manifest(base_id)
    path = "tool-guidance.md"
    raw = store.get_blob(base.components[path])
    first = proposal(
        store,
        base_id,
        path,
        raw.replace(b"No prose, no markdown fences.", b"No prose; verify all outputs.", 1),
    )
    second = proposal(
        store,
        base_id,
        path,
        raw.replace(b"Prefer search.text", b"Carefully prefer search.text"),
        scope="domain",
    )
    result = compose_proposals(store, base_id, (first, second, first))
    assert not result.conflicts
    merged = store.get_blob(store.get_manifest(result.candidate_id).components[path])
    assert b"No prose; verify all outputs." in merged and b"Carefully prefer search.text" in merged
    assert merged.count(b"No prose; verify all outputs.") == 1


def test_overlapping_and_same_position_insertions_report_conflicts_without_writes(tmp_path):
    store, base_id = setup_store(tmp_path)
    path = "prompts/forge.md"
    base = store.get_blob(store.get_manifest(base_id).components[path])
    a = proposal(store, base_id, path, base.replace(b"## job\n", b"## job\nFirst\n"))
    b = proposal(store, base_id, path, base.replace(b"## job\n", b"## job\nSecond\n"))
    before = {p.name for p in store.objects.iterdir()}
    result = compose_proposals(store, base_id, (a, b))
    assert result.candidate_id is None and result.changed_paths == ()
    assert len(result.conflicts) == 1
    assert (result.conflicts[0].path, result.conflicts[0].first, result.conflicts[0].second) == (
        path,
        0,
        1,
    )
    assert {p.name for p in store.objects.iterdir()} == before


def test_overlapping_replacements_return_conflict(tmp_path):
    store, base_id = setup_store(tmp_path)
    path = "prompts/forge.md"
    base = store.get_blob(store.get_manifest(base_id).components[path])
    a = proposal(store, base_id, path, base.replace(b"you execute", b"You carefully execute"))
    b = proposal(store, base_id, path, base.replace(b"you execute", b"You quickly execute"))
    assert compose_proposals(store, base_id, (a, b)).conflicts


def test_forged_and_invalid_proposals_fail_closed(tmp_path):
    store, base_id = setup_store(tmp_path)
    path = "prompts/forge.md"
    base = store.get_blob(store.get_manifest(base_id).components[path])
    good = proposal(store, base_id, path, base + b"extra\n")
    invalid = [
        replace(good, before_hash="0" * 64),
        replace(good, after=b"fake\n"),
        replace(good, path="guardrails/policy.yaml"),
        replace(good, scope=[]),
        replace(good, diff="bad"),
    ]
    for value in invalid:
        with pytest.raises(HarnessError):
            compose_proposals(store, base_id, (value,))
    for proposals in ((), (good,) * 11, [good], (object(),)):
        with pytest.raises(HarnessError):
            compose_proposals(store, base_id, proposals)


def test_protected_baseline_and_invalid_composed_prompt_rejected(tmp_path):
    store, base_id = setup_store(tmp_path)
    base = store.get_manifest(base_id)
    components = dict(base.components)
    components["guardrails/policy.yaml"] = store.put_blob(b"unsafe\n")
    bad_id = store.put_manifest(Manifest(1, base.model_pin, MappingProxyType(components)))
    path = "prompts/forge.md"
    raw = store.get_blob(base.components[path])
    good = proposal(store, bad_id, path, raw + b"extra\n")
    with pytest.raises(HarnessError, match="protected baseline"):
        compose_proposals(store, bad_id, (good,))
    bad_prompt = proposal(store, base_id, path, raw.replace(b"## job", b"## invalid"))
    with pytest.raises(HarnessError):
        compose_proposals(store, base_id, (bad_prompt,))


def test_corrupt_baseline_object_is_rejected(tmp_path):
    store, base_id = setup_store(tmp_path)
    base = store.get_manifest(base_id)
    path = "prompts/forge.md"
    raw = store.get_blob(base.components[path])
    p = proposal(store, base_id, path, raw + b"extra\n")
    (store.objects / base.components[path]).write_bytes(b"tampered")
    with pytest.raises(HarnessError, match="integrity"):
        compose_proposals(store, base_id, (p,))
