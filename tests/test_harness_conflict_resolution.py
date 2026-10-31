"""Offline conflict handoff: untrusted callback, no execution or adoption."""

from __future__ import annotations

import difflib
import json

import pytest
from test_harness_composer import proposal
from test_harness_editor import setup_store

from arcen.harness.composer import compose_proposals, preview_proposals
from arcen.harness.conflict_resolution import draft_conflict_resolutions
from arcen.harness.policy import AdoptionUnavailable, adopt_candidate
from arcen.harness.resolver import HarnessError


def fixture(tmp_path):
    store, baseline = setup_store(tmp_path)
    manifest = store.get_manifest(baseline)
    path = "prompts/forge.md"
    raw = store.get_blob(manifest.components[path])
    one = proposal(store, baseline, path, raw.replace(b"## job\n", b"## job\nFirst edit.\n"))
    two = proposal(store, baseline, path, raw.replace(b"## job\n", b"## job\nSecond edit.\n"))
    other_path = "prompts/temper.md"
    other = store.get_blob(manifest.components[other_path])
    third = proposal(store, baseline, other_path, other + b"Check outcome.\n")
    return store, baseline, path, raw, (one, two, third)


def patch(path, original, after):
    return "".join(
        difflib.unified_diff(
            original.decode().splitlines(True),
            after.decode().splitlines(True),
            fromfile="a/" + path,
            tofile="b/" + path,
        )
    )


def test_conflicts_go_to_editor_and_return_only_unpersisted_draft(tmp_path):
    store, baseline, path, original, proposals = fixture(tmp_path)
    before = {p.name for p in store.objects.iterdir()}
    seen = []

    def editor(request):
        seen.append(request)
        merged = original.replace(b"## job\n", b"## job\nCombined edit.\n")
        return json.dumps({"path": path, "diff": patch(path, original, merged)})

    draft = draft_conflict_resolutions(
        store, baseline, proposals, editor, reviewed_callback_inputs=True
    )
    assert len(seen) == 1 and seen[0]["baseline"] == original.decode()
    assert [p["index"] for p in seen[0]["proposals"]] == [0, 1]
    assert seen[0]["conflicts"] == [{"first": 0, "second": 1}]
    assert draft.replaced_paths == (path,) and len(draft.original_conflicts) == 1
    assert draft.preview.changed_paths == (path, "prompts/temper.md")
    assert not draft.preview.conflicts and len(draft.proposals) == 2
    assert {p.name for p in store.objects.iterdir()} == before
    assert not (store.root / "lineage.sqlite3").exists()
    result = compose_proposals(store, baseline, draft.proposals)
    assert result.candidate_id and not result.conflicts
    manifest = store.get_manifest(result.candidate_id)
    assert b"Combined edit." in store.get_blob(manifest.components[path])
    with pytest.raises(AdoptionUnavailable):
        adopt_candidate(store, baseline, result.candidate_id)


def test_preview_does_not_write_even_without_conflict(tmp_path):
    store, baseline, path, _, proposals = fixture(tmp_path)
    before = {p.name for p in store.objects.iterdir()}
    preview = preview_proposals(store, baseline, (proposals[0], proposals[2]))
    assert preview.changed_paths == (path, "prompts/temper.md") and not preview.conflicts
    assert {p.name for p in store.objects.iterdir()} == before


def test_review_and_conflict_preflight_precede_callback_and_writes(tmp_path):
    store, baseline, _, _, proposals = fixture(tmp_path)
    before = {p.name for p in store.objects.iterdir()}
    callback = lambda _: pytest.fail("callback invoked")
    for flag in (False, 1, "yes"):
        with pytest.raises(HarnessError, match="explicit review"):
            draft_conflict_resolutions(
                store, baseline, proposals, callback, reviewed_callback_inputs=flag
            )
    with pytest.raises(HarnessError, match="requires conflicting"):
        draft_conflict_resolutions(
            store, baseline, (proposals[0],), callback, reviewed_callback_inputs=True
        )
    assert {p.name for p in store.objects.iterdir()} == before


@pytest.mark.parametrize(
    "response",
    [
        "not json",
        "{}",
        '{"path":"x","path":"x","diff":"x"}',
        '{"path":"guardrails/policy.yaml","diff":"x"}',
        '{"path":"prompts/forge.md","diff":7}',
        '{"path":"prompts/forge.md","diff":"x","extra":1}',
        "x" * (70 * 1024),
    ],
)
def test_untrusted_invalid_responses_fail_without_writes(tmp_path, response):
    store, baseline, _, _, proposals = fixture(tmp_path)
    before = {p.name for p in store.objects.iterdir()}
    with pytest.raises(HarnessError, match="invalid replacement"):
        draft_conflict_resolutions(
            store, baseline, proposals, lambda _: response, reviewed_callback_inputs=True
        )
    assert {p.name for p in store.objects.iterdir()} == before


def test_callback_error_is_sanitized_and_no_draft_is_accepted(tmp_path):
    store, baseline, _, _, proposals = fixture(tmp_path)
    before = {p.name for p in store.objects.iterdir()}

    def bad(_):
        raise RuntimeError("private model response")

    with pytest.raises(HarnessError, match="conflict editor failed") as err:
        draft_conflict_resolutions(store, baseline, proposals, bad, reviewed_callback_inputs=True)
    assert "private" not in str(err.value)
    assert {p.name for p in store.objects.iterdir()} == before


def test_same_path_nonconflicting_proposals_are_also_exposed_and_superseded(tmp_path):
    store, baseline, path, original, proposals = fixture(tmp_path)
    extra = proposal(store, baseline, path, original + b"Also check output.\n")
    seen = []

    def editor(request):
        seen.append(request)
        return json.dumps({"path": path, "diff": proposals[0].diff})

    draft = draft_conflict_resolutions(
        store, baseline, (*proposals, extra), editor, reviewed_callback_inputs=True
    )
    assert [p["index"] for p in seen[0]["proposals"]] == [0, 1, 3]
    result_for_path = next(item for item in draft.proposals if item.path == path)
    assert b"Also check output." not in result_for_path.after
    assert draft.preview.changed_paths == (path, "prompts/temper.md")


def test_two_conflicting_paths_return_separate_replacements_in_stable_order(tmp_path):
    store, baseline, path, original, proposals = fixture(tmp_path)
    other_path = "prompts/temper.md"
    other = store.get_blob(store.get_manifest(baseline).components[other_path])
    left = proposal(store, baseline, other_path, other + b"First tail.\n")
    right = proposal(store, baseline, other_path, other + b"Second tail.\n")
    seen = []

    def editor(request):
        seen.append(request["path"])
        if request["path"] == path:
            value = proposals[0].diff
        else:
            value = left.diff
        return json.dumps({"path": request["path"], "diff": value})

    before = {p.name for p in store.objects.iterdir()}
    result = draft_conflict_resolutions(
        store, baseline, (*proposals[:2], left, right), editor, reviewed_callback_inputs=True
    )
    assert seen == [path, other_path] and result.replaced_paths == (path, other_path)
    assert len(result.proposals) == 2 and not result.preview.conflicts
    assert {p.name for p in store.objects.iterdir()} == before
    assert b"First edit." in result.proposals[0].after
    assert original != result.proposals[0].after


def test_second_editor_failure_never_persists_first_replacement(tmp_path):
    store, baseline, path, _, proposals = fixture(tmp_path)
    other_path = "prompts/temper.md"
    other = store.get_blob(store.get_manifest(baseline).components[other_path])
    left = proposal(store, baseline, other_path, other + b"One.\n")
    right = proposal(store, baseline, other_path, other + b"Two.\n")
    seen = []

    def editor(request):
        seen.append(request["path"])
        if request["path"] == path:
            return json.dumps({"path": path, "diff": proposals[0].diff})
        return "invalid"

    before = {p.name for p in store.objects.iterdir()}
    with pytest.raises(HarnessError, match="invalid replacement"):
        draft_conflict_resolutions(
            store, baseline, (*proposals[:2], left, right), editor, reviewed_callback_inputs=True
        )
    assert seen == [path, other_path]
    assert {p.name for p in store.objects.iterdir()} == before


def test_replacement_must_still_satisfy_full_prompt_validation(tmp_path):
    store, baseline, path, original, proposals = fixture(tmp_path)
    invalid = original.replace(b"## job", b"## invalid")
    before = {p.name for p in store.objects.iterdir()}
    with pytest.raises(HarnessError):
        draft_conflict_resolutions(
            store,
            baseline,
            proposals,
            lambda _: json.dumps({"path": path, "diff": patch(path, original, invalid)}),
            reviewed_callback_inputs=True,
        )
    assert {p.name for p in store.objects.iterdir()} == before
