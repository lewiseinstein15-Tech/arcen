"""Reviewed parallel reference/candidate trials: provider and Docker mocked."""

from __future__ import annotations

import threading
import time
from dataclasses import replace

import litellm
import pytest
from test_harness_probe import changed
from test_manual_campaign import setup
from test_probe_execution import Boundary
from test_probe_model import response

from arcen.harness import HarnessError, parallel_trials, probe_container
from arcen.harness.budget import SharedBudget, TrialConcurrencyFull
from arcen.harness.cli import _init
from arcen.harness.lineage import HarnessLineage
from arcen.harness.probe_execution import ReviewedProbeResult


def terminal(status):
    return ({"type": "run.done", "status": status},)


def cap(**kwargs):
    return SharedBudget(
        **(
            {
                "max_trials": 5,
                "max_model_calls": 12,
                "max_judge_calls": 0,
                "admission_seconds": 120,
                "max_concurrent_trials": 2,
            }
            | kwargs
        )
    )


def run(args, budget, **kwargs):
    store, baseline, candidates, cfg, repo, commit, _ = args
    options = {
        "repo": repo,
        "commit": commit,
        "budget": budget,
        "workers": 2,
        "reviewed_inputs": True,
    }
    options.update(kwargs)
    return parallel_trials.run_reviewed_parallel_trials(
        store, baseline, candidates, "inspect project", cfg, **options
    )


def three_candidates(args):
    store, baseline, candidates, cfg, repo, commit, ledger = args
    base = store.get_manifest(baseline)
    path = "prompts/temper.md"
    third = changed(
        store, base, path, store.get_blob(base.components[path]) + b"review carefully\n"
    )
    return store, baseline, (*candidates, third), cfg, repo, commit, ledger


def test_real_probe_pipeline_uses_one_snapshot_and_never_selects_or_adopts(tmp_path, monkeypatch):
    args = setup(tmp_path)
    store, baseline, candidates, _, repo, commit, _ = args
    adopted = _init(str(store.root))
    budget = cap()
    Boundary.instances.clear()
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        content = kwargs["messages"][-1]["content"]
        return response("answer based on the mock" if content == "inspect project" else "DIRECT")

    monkeypatch.setattr(litellm, "completion", completion)
    original = parallel_trials.snapshot_git_commit
    snapshots = []

    def capture(*a):
        value = original(*a)
        snapshots.append(value.sha256)
        return value

    monkeypatch.setattr(parallel_trials, "snapshot_git_commit", capture)
    result = run(args, budget)
    assert result.stop_reason is None and result.unstarted == ()
    assert result.reference.status == "ok" and result.reference.candidate_id == baseline
    assert [item.candidate_id for item in result.candidates] == list(candidates)
    assert all(item.status == "ok" for item in result.candidates)
    assert len(snapshots) == 1 and result.workspace_sha256 == snapshots[0]
    assert all(
        item.result.workspace_sha256 == snapshots[0] and item.result.commit == commit
        for item in (result.reference, *result.candidates)
    )
    assert (budget.snapshot().trials, budget.snapshot().model_calls) == (3, 6)
    assert len(calls) == 6 and budget.active_trials == 0
    assert len(Boundary.instances) == 3
    assert all(item.closed and not item.workspace.exists() for item in Boundary.instances)
    assert (repo / "src/main.py").read_text() == "print('committed')\n"
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted


def test_waves_run_in_parallel_but_preserve_result_order(tmp_path, monkeypatch):
    args = three_candidates(setup(tmp_path))
    baseline = args[1]
    budget = cap()
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    state = {"active": 0, "peak": 0, "candidate_count": 0}

    def execute(_self, snapshot, cfg, model):
        budget.reserve_trial()
        identifier = model.plan.candidate_id
        if identifier != baseline:
            with lock:
                state["active"] += 1
                state["candidate_count"] += 1
                ordinal = state["candidate_count"]
                state["peak"] = max(state["peak"], state["active"])
            try:
                if ordinal <= 2:
                    barrier.wait(timeout=10)
                time.sleep(0.02)
            finally:
                with lock:
                    state["active"] -= 1
        return ReviewedProbeResult(
            baseline, identifier, snapshot.commit, snapshot.sha256, "ok", terminal("ok")
        )

    monkeypatch.setattr(parallel_trials.NativeDockerProbeExecutor, "execute", execute)
    result = run(args, budget)
    assert result.stop_reason is None and result.unstarted == ()
    assert [item.candidate_id for item in result.candidates] == list(args[2])
    assert state["peak"] == 2 and state["active"] == 0
    assert budget.snapshot().trials == 4


def test_failed_wave_prevents_later_candidates_but_keeps_inflight_results(tmp_path, monkeypatch):
    args = three_candidates(setup(tmp_path))
    baseline, first, second, third = args[1], *args[2]
    budget = cap()
    seen = []

    def execute(_self, snapshot, cfg, model):
        identifier = model.plan.candidate_id
        seen.append(identifier)
        budget.reserve_trial()
        return ReviewedProbeResult(
            baseline,
            identifier,
            snapshot.commit,
            snapshot.sha256,
            "failed" if identifier == first else "ok",
            terminal("failed" if identifier == first else "ok"),
        )

    monkeypatch.setattr(parallel_trials.NativeDockerProbeExecutor, "execute", execute)
    result = run(args, budget)
    assert result.stop_reason == "candidate_wave_failed" and result.unstarted == (third,)
    assert [item.candidate_id for item in result.candidates] == [first, second]
    assert [item.status for item in result.candidates] == ["failed", "ok"]
    assert third not in seen and budget.snapshot().trials == 3


def test_reference_failure_stops_before_candidates(tmp_path, monkeypatch):
    args = setup(tmp_path)
    baseline = args[1]
    budget = cap()

    def execute(_self, snapshot, cfg, model):
        budget.reserve_trial()
        return ReviewedProbeResult(
            baseline,
            model.plan.candidate_id,
            snapshot.commit,
            snapshot.sha256,
            "failed",
            terminal("failed"),
        )

    monkeypatch.setattr(parallel_trials.NativeDockerProbeExecutor, "execute", execute)
    result = run(args, budget)
    assert result.stop_reason == "reference_failed" and result.unstarted == args[2]
    assert result.candidates == () and budget.snapshot().trials == 1


def test_concurrency_full_is_not_reported_as_budget_closed(tmp_path, monkeypatch):
    args = setup(tmp_path)
    budget = cap()
    monkeypatch.setattr(
        parallel_trials.NativeDockerProbeExecutor,
        "execute",
        lambda *a: (_ for _ in ()).throw(TrialConcurrencyFull("details")),
    )
    result = run(args, budget)
    assert result.stop_reason == "reference_concurrency_full" and result.unstarted == args[2]
    assert not budget.snapshot().stopped and budget.snapshot().trials == 0


def test_uncertain_executor_error_latches_budget_without_exposing_details(tmp_path, monkeypatch):
    args = setup(tmp_path)
    budget = cap()
    monkeypatch.setattr(
        parallel_trials.NativeDockerProbeExecutor,
        "execute",
        lambda *a: (_ for _ in ()).throw(ValueError("private details")),
    )
    result = run(args, budget)
    assert result.stop_reason == "reference_unavailable" and "private details" not in repr(result)
    assert budget.snapshot().stopped and result.unstarted == args[2]


def test_preflight_rejects_invalid_inputs_before_any_executor(tmp_path, monkeypatch):
    args = setup(tmp_path)
    budget = cap()
    monkeypatch.setattr(
        parallel_trials.NativeDockerProbeExecutor,
        "execute",
        lambda *a: pytest.fail("unexpected trial"),
    )
    for values in (
        {"reviewed_inputs": False},
        {"workers": True},
        {"workers": 3},
        {"expected_workspace_sha256": "0" * 64},
    ):
        with pytest.raises(HarnessError):
            run(args, budget, **values)
    store, baseline, candidates, cfg, repo, commit, ledger = args
    with pytest.raises(HarnessError):
        run((store, baseline, (candidates[0], candidates[0]), cfg, repo, commit, ledger), budget)
    cfg.sandbox.backend = "process"
    with pytest.raises(HarnessError, match="Docker"):
        run(args, budget)
    assert budget.snapshot().trials == budget.snapshot().model_calls == 0


def test_known_secret_in_snapshot_refused_before_trial(tmp_path, monkeypatch):
    args = setup(tmp_path)
    budget = cap()
    monkeypatch.setattr(
        parallel_trials.NativeDockerProbeExecutor,
        "execute",
        lambda *a: pytest.fail("unexpected trial"),
    )
    original = parallel_trials.snapshot_git_commit
    monkeypatch.setattr(
        parallel_trials,
        "snapshot_git_commit",
        lambda *a: replace(original(*a), archive=original(*a).archive + b"workspace-secret-marker"),
    )
    with pytest.raises(HarnessError, match="sensitive"):
        run(args, budget, sensitive_values=("workspace-secret-marker",))
    assert budget.snapshot().trials == budget.snapshot().model_calls == 0


def test_stop_after_reference_prevents_any_candidate_submission(tmp_path, monkeypatch):
    args = setup(tmp_path)
    budget = cap()
    seen = []

    def execute(_self, snapshot, cfg, model):
        seen.append(model.plan.candidate_id)
        budget.reserve_trial()
        budget.stop()
        return ReviewedProbeResult(
            args[1], model.plan.candidate_id, snapshot.commit, snapshot.sha256, "ok", terminal("ok")
        )

    monkeypatch.setattr(parallel_trials.NativeDockerProbeExecutor, "execute", execute)
    result = run(args, budget)
    assert seen == [args[1]] and result.stop_reason == "budget_closed"
    assert result.candidates == () and result.unstarted == args[2]


def test_mismatched_executor_result_fails_closed_and_stops_budget(tmp_path, monkeypatch):
    args = setup(tmp_path)
    budget = cap()

    def execute(_self, snapshot, cfg, model):
        return ReviewedProbeResult(
            args[1], model.plan.candidate_id, snapshot.commit, "0" * 64, "ok", terminal("ok")
        )

    monkeypatch.setattr(parallel_trials.NativeDockerProbeExecutor, "execute", execute)
    result = run(args, budget)
    assert result.stop_reason == "reference_unavailable" and result.unstarted == args[2]
    assert budget.snapshot().stopped


def test_cleanup_failure_stops_budget_and_does_not_expose_details(tmp_path, monkeypatch):
    args = setup(tmp_path)
    budget = cap()
    Boundary.instances.clear()

    class FailedCleanup(Boundary):
        fail_close = True

    monkeypatch.setattr(probe_container, "DockerTurnRegistry", FailedCleanup)
    monkeypatch.setattr(
        litellm,
        "completion",
        lambda **kwargs: response(
            "answer" if kwargs["messages"][-1]["content"] == "inspect project" else "DIRECT"
        ),
    )
    result = run(args, budget)
    assert result.stop_reason == "reference_unavailable" and result.unstarted == args[2]
    assert budget.snapshot().stopped and budget.active_trials == 0
    assert "secret exception" not in repr(result)
    assert len(Boundary.instances) == 1 and Boundary.instances[0].closed
    assert not Boundary.instances[0].workspace.exists()


def test_partial_submission_waits_for_started_work_and_reports_unstarted(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    args = three_candidates(setup(tmp_path))
    budget = cap()
    finished = []
    started = threading.Event()

    def execute(_self, snapshot, cfg, model):
        budget.reserve_trial()
        identifier = model.plan.candidate_id
        if identifier != args[1]:
            started.set()
            time.sleep(0.05)
            finished.append(identifier)
        return ReviewedProbeResult(
            args[1], identifier, snapshot.commit, snapshot.sha256, "ok", terminal("ok")
        )

    class BrokenPool(ThreadPoolExecutor):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.submissions = 0

        def submit(self, *args, **kwargs):
            self.submissions += 1
            if self.submissions == 2:
                assert started.wait(timeout=10)
                raise RuntimeError("private scheduler detail")
            return super().submit(*args, **kwargs)

    monkeypatch.setattr(parallel_trials.NativeDockerProbeExecutor, "execute", execute)
    monkeypatch.setattr(parallel_trials, "ThreadPoolExecutor", BrokenPool)
    result = run(args, budget)
    assert result.stop_reason == "scheduler_unavailable" and budget.snapshot().stopped
    assert finished == [args[2][0]]
    assert [attempt.candidate_id for attempt in result.candidates] == [args[2][0]]
    assert result.unstarted == args[2][1:]
    assert "private scheduler detail" not in repr(result)
