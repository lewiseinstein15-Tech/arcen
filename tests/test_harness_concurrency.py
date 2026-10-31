"""Optional in-process trial concurrency cap; no cross-process guarantee."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
from test_harness_comparison import provider
from test_probe_execution import Boundary
from test_probe_model import configured
from test_probe_workspace import repository

from arcen.harness import probe_container, probe_execution
from arcen.harness.budget import BudgetExhausted, SharedBudget
from arcen.harness.probe import ProbeUnavailable
from arcen.harness.probe_execution import run_reviewed_probe
from arcen.harness.resolver import HarnessError


def make_budget(**changes):
    options = {
        "max_trials": 4,
        "max_model_calls": 8,
        "max_judge_calls": 2,
        "admission_seconds": 120,
        "max_concurrent_trials": 1,
    }
    options.update(changes)
    return SharedBudget(**options)


@pytest.mark.parametrize("value", [True, 0, -1, 1.0, "2", 100001])
def test_invalid_concurrency_is_rejected(value):
    with pytest.raises(HarnessError, match="concurrency"):
        make_budget(max_concurrent_trials=value)


def test_concurrent_trials_are_refused_without_spending_or_latching(tmp_path, monkeypatch):
    store, baseline, candidate, cfg = configured(tmp_path)
    repo, commit = repository(tmp_path)
    cap = make_budget()
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    real = probe_execution.open_probe_container
    entered, release = threading.Event(), threading.Event()

    @contextmanager
    def wait_container(*args, **kwargs):
        entered.set()
        if not release.wait(15):
            raise RuntimeError("test timeout")
        with real(*args, **kwargs) as container:
            yield container

    monkeypatch.setattr(probe_execution, "open_probe_container", wait_container)

    def run():
        return run_reviewed_probe(
            store,
            baseline,
            candidate,
            "inspect project",
            cfg,
            repo=repo,
            commit=commit,
            reviewed_inputs=True,
            budget=cap,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run)
        try:
            assert entered.wait(10) and cap.active_trials == 1
            with pytest.raises(BudgetExhausted, match="concurrency full"):
                run()
            assert cap.snapshot().trials == 1 and not cap.snapshot().stopped and not calls
        finally:
            release.set()
        result = first.result(timeout=15)
    assert result.status == "ok" and cap.active_trials == 0
    assert len(calls) == 2 and not cap.snapshot().stopped
    assert run().status == "ok" and cap.snapshot().trials == 2


def test_uncertain_cleanup_latches_budget_closed(tmp_path, monkeypatch):
    store, baseline, candidate, cfg = configured(tmp_path)
    repo, commit = repository(tmp_path)
    cap = make_budget()

    class BadCleanup(Boundary):
        def close(self, *, strict=False):
            raise RuntimeError("uncertain cleanup")

    monkeypatch.setattr(probe_container, "DockerTurnRegistry", BadCleanup)
    provider(monkeypatch)
    with pytest.raises(ProbeUnavailable, match="isolation or cleanup"):
        run_reviewed_probe(
            store,
            baseline,
            candidate,
            "inspect project",
            cfg,
            repo=repo,
            commit=commit,
            reviewed_inputs=True,
            budget=cap,
        )
    assert cap.active_trials == 0 and cap.snapshot().stopped
    with pytest.raises(BudgetExhausted, match="stopped"):
        cap.checkpoint()


def test_stop_does_not_cancel_an_already_acquired_slot():
    cap = make_budget()
    with cap._trial_slot():
        cap.stop()
        assert cap.active_trials == 1
    assert cap.active_trials == 0 and cap.snapshot().stopped


def test_manual_campaign_reports_full_slot_without_claiming_budget_closed(tmp_path, monkeypatch):
    from test_manual_campaign import run, setup

    args = setup(tmp_path)
    cap = make_budget()
    events = []
    monkeypatch.setattr(
        probe_container, "DockerTurnRegistry", lambda *a, **kw: pytest.fail("docker")
    )
    with cap._trial_slot():
        result = run(args, budget=cap, on_progress=events.append)
    assert result.stop_reason == "concurrency_full" and result.reference is None
    assert events[-1]["reason"] == "concurrency_full" and events[-1]["status"] == "stopped"
    assert cap.snapshot().trials == 0 and not cap.snapshot().stopped
