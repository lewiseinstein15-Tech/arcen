"""Editor → composer → paired trial → judge without adoption."""

from __future__ import annotations

import difflib
import json

import litellm
import pytest
from test_harness_comparison import provider
from test_harness_composer import proposal
from test_probe_execution import Boundary
from test_probe_model import configured
from test_probe_workspace import repository

from arcen.harness import HarnessError, comparison, probe_container
from arcen.harness.editor import propose
from arcen.harness.proposal_comparison import compare_reviewed_proposals


def test_editor_proposals_flow_through_composition_trials_and_judge(tmp_path, monkeypatch):
    store, baseline, _, cfg = configured(tmp_path)
    repo, commit = repository(tmp_path)

    def editor(request):
        path = "tool-guidance.md"
        original = request["components"][path]
        edited = original.replace("No prose, no markdown fences.", "Verify all observations.", 1)
        patch = "".join(
            difflib.unified_diff(
                original.splitlines(True),
                edited.splitlines(True),
                fromfile="a/" + path,
                tofile="b/" + path,
            )
        )
        return json.dumps({"path": path, "diff": patch})

    proposals = propose(store, baseline, "inspect project", (editor,), k=1)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    judged = []

    def judge(request):
        judged.append(request)
        return '{"winner":"tie","confidence":0.6,"reason":"equivalent"}'

    result = compare_reviewed_proposals(
        store,
        baseline,
        proposals,
        "inspect project",
        cfg,
        judge,
        repo=repo,
        commit=commit,
        reviewed_inputs=True,
        reviewed_judge_inputs=True,
    )
    assert result.composition.candidate_id is not None and not result.composition.conflicts
    assert result.comparison.judgment.winner == "tie"
    assert result.comparison.reference.status == result.comparison.candidate.status == "ok"
    assert result.comparison.candidate.candidate_id == result.composition.candidate_id
    assert len(calls) == 4 and len(judged) == 1
    assert not (store.root / "lineage.sqlite3").exists()  # no ref, approval, or adoption


def test_conflicting_proposals_stop_before_git_docker_model_or_judge(tmp_path, monkeypatch):
    store, baseline, _, cfg = configured(tmp_path)
    base = store.get_manifest(baseline)
    path = "prompts/forge.md"
    raw = store.get_blob(base.components[path])
    first = proposal(store, baseline, path, raw.replace(b"## job\n", b"## job\nFirst\n"))
    second = proposal(store, baseline, path, raw.replace(b"## job\n", b"## job\nSecond\n"))
    before = {p.name for p in store.objects.iterdir()}
    monkeypatch.setattr(comparison, "snapshot_git_commit", lambda *_: pytest.fail("Git called"))
    monkeypatch.setattr(litellm, "completion", lambda **_: pytest.fail("provider called"))
    result = compare_reviewed_proposals(
        store,
        baseline,
        (first, second),
        "task",
        cfg,
        lambda _: pytest.fail("judge called"),
        repo="/missing",
        commit="bad",
        reviewed_inputs=True,
        reviewed_judge_inputs=True,
    )
    assert result.composition.conflicts and result.composition.candidate_id is None
    assert result.comparison is None and before == {p.name for p in store.objects.iterdir()}


def test_review_attestations_required_before_store_writes(tmp_path, monkeypatch):
    store, baseline, _, cfg = configured(tmp_path)
    raw = store.get_blob(store.get_manifest(baseline).components["prompts/forge.md"])
    p = proposal(store, baseline, "prompts/forge.md", raw + b"extra\n")
    before = {p.name for p in store.objects.iterdir()}
    for left, right in ((False, False), (True, False), (False, True)):
        with pytest.raises(HarnessError, match="explicit review"):
            compare_reviewed_proposals(
                store,
                baseline,
                (p,),
                "task",
                cfg,
                lambda _: "",
                repo="/missing",
                commit="bad",
                reviewed_inputs=left,
                reviewed_judge_inputs=right,
            )
    assert before == {p.name for p in store.objects.iterdir()}
