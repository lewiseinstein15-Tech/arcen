"""Local attribution checks; not executor authentication or safety proof."""

from __future__ import annotations

from dataclasses import replace

import pytest
from test_campaign_journal import plan
from test_harness_canary import run as run_canaries
from test_harness_canary import setup as setup_canaries
from test_harness_comparison import provider
from test_manual_campaign import budget, run, setup
from test_probe_execution import Boundary
from test_probe_model import configured
from test_probe_workspace import repository

from arcen.harness import canary, comparison, manual_campaign, probe_container
from arcen.harness.comparison import run_reviewed_comparison
from arcen.harness.probe import ProbeUnavailable
from arcen.harness.progress import _validate


def corrupt(result, field):
    if field == "result_type":
        return None
    updates = {
        "baseline_id": "0" * 64,
        "candidate_id": "0" * 64,
        "commit": "0" * 40,
        "workspace_sha256": "0" * 64,
        "status": "unexpected",
        "events": (),
        "terminal_status": ({"type": "run.done", "status": "failed"},),
        "terminal_type": ({"type": "run.error"},),
    }
    key = "events" if field in {"terminal_status", "terminal_type"} else field
    return replace(result, **{key: updates[field]})


@pytest.mark.parametrize("which", [1, 2, 3])
@pytest.mark.parametrize(
    "field",
    [
        "baseline_id",
        "candidate_id",
        "commit",
        "workspace_sha256",
        "status",
        "events",
        "terminal_status",
        "terminal_type",
        "result_type",
    ],
)
def test_campaign_stops_before_attributing_mismatched_result(tmp_path, monkeypatch, which, field):
    args = setup(tmp_path)
    journal, record = plan(args)
    cap = budget()
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    original = manual_campaign._run_bound_probe
    seen = 0

    def wrapped(*a, **kw):
        nonlocal seen
        result = original(*a, **kw)
        seen += 1
        return corrupt(result, field) if seen == which else result

    monkeypatch.setattr(manual_campaign, "_run_bound_probe", wrapped)
    progress = []
    result = run(
        args, budget=cap, journal=journal, campaign_id=record.id, on_progress=progress.append
    )
    expected = "reference_result_mismatch" if which == 1 else "candidate_result_mismatch"
    assert result.stop_reason == expected
    assert seen == which and len(calls) == which * 2
    assert len(result.completed) == max(0, which - 2)
    assert cap.snapshot().judge_calls == max(0, which - 2)
    assert len(args[-1].list()) == max(0, which - 2)
    assert journal.get(record.id).state == "failed"
    assert journal.get(record.id).cursor == max(0, which - 2)
    assert progress[-1]["reason"] == expected
    for event in progress:
        _validate(event)
    if which == 1:
        assert result.reference is None and result.stopped_candidate is None
    else:
        assert result.stopped_candidate == args[2][which - 2]


@pytest.mark.parametrize("which", [1, 2])
@pytest.mark.parametrize(
    "field",
    [
        "baseline_id",
        "candidate_id",
        "commit",
        "workspace_sha256",
        "status",
        "events",
        "terminal_status",
        "terminal_type",
        "result_type",
    ],
)
def test_paired_comparison_rejects_mismatch_before_judge(tmp_path, monkeypatch, which, field):
    store, baseline, candidate, cfg = configured(tmp_path)
    repo, commit = repository(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    provider_calls = provider(monkeypatch)
    original = comparison.NativeDockerProbeExecutor.execute
    seen = 0

    def wrapped(self, *a, **kw):
        nonlocal seen
        result = original(self, *a, **kw)
        seen += 1
        return corrupt(result, field) if seen == which else result

    monkeypatch.setattr(comparison.NativeDockerProbeExecutor, "execute", wrapped)
    with pytest.raises(ProbeUnavailable, match="did not match"):
        run_reviewed_comparison(
            store,
            baseline,
            candidate,
            "inspect project",
            cfg,
            lambda _: pytest.fail("judge must not run"),
            repo=repo,
            commit=commit,
            reviewed_inputs=True,
            reviewed_judge_inputs=True,
        )
    assert seen == which and len(provider_calls) == which * 2


@pytest.mark.parametrize("which", [1, 2])
@pytest.mark.parametrize(
    "field",
    [
        "baseline_id",
        "candidate_id",
        "commit",
        "workspace_sha256",
        "status",
        "events",
        "terminal_status",
        "terminal_type",
        "result_type",
    ],
)
def test_canary_mismatch_is_inconclusive_not_a_pass_or_regression(
    tmp_path, monkeypatch, which, field
):
    args = setup_canaries(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    provider_calls = provider(monkeypatch)
    original = canary._run_bound_probe
    seen = 0

    def wrapped(*a, **kw):
        nonlocal seen
        result = original(*a, **kw)
        seen += 1
        return corrupt(result, field) if seen == which else result

    monkeypatch.setattr(canary, "_run_bound_probe", wrapped)
    report = run_canaries(args)
    assert report.outcome == "inconclusive" and len(report.findings) == 1
    assert (report.findings[0].reference, report.findings[0].candidate) == (
        ("inconclusive", "not-run") if which == 1 else ("passed", "inconclusive")
    )
    assert seen == which and len(provider_calls) == which * 2
