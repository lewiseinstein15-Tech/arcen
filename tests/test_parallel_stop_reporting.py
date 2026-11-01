"""Budget-stop outcome is reported without promising a universal kill switch."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_durable_budget import create
from test_harness_parallel_trials import cap, run, terminal, three_candidates
from test_manual_campaign import setup
from test_probe_result_binding import corrupt

from arcen.harness import parallel_trials
from arcen.harness.durable_trial_slots import DurableTrialSlots
from arcen.harness.probe_execution import ReviewedProbeResult

SECRET = "private-budget-storage-error"


def valid(args, snapshot, model):
    return ReviewedProbeResult(
        args[1], model.plan.candidate_id, snapshot.commit, snapshot.sha256, "ok", terminal("ok")
    )


def deny_stop():
    raise OSError(SECRET)


@pytest.mark.parametrize("durable", [False, True])
def test_reference_stop_failure_is_visible_and_never_leaks(tmp_path, monkeypatch, durable):
    args = setup(tmp_path)
    budget = create(args[0]) if durable else cap()
    slots = DurableTrialSlots.create(budget, max_active=2) if durable else None
    seen = []

    def execute(_self, snapshot, _cfg, model):
        seen.append(model.plan.candidate_id)
        budget.reserve_trial()
        return corrupt(valid(args, snapshot, model), "terminal_type")

    monkeypatch.setattr(parallel_trials.NativeDockerProbeExecutor, "execute", execute)
    monkeypatch.setattr(budget, "stop", deny_stop)
    report = run(args, budget, durable_slots=slots) if durable else run(args, budget)
    assert report.stop_reason == "reference_unavailable" and report.reference.result is None
    assert report.unstarted == args[2] and seen == [args[1]]
    assert report.budget_stop_call_succeeded is False and not budget.snapshot().stopped
    assert SECRET not in repr(report)
    if durable:
        assert slots.snapshot().occupied == 1


@pytest.mark.parametrize("durable", [False, True])
def test_failed_stop_still_waits_for_peer_and_starts_no_later_wave(tmp_path, monkeypatch, durable):
    args = three_candidates(setup(tmp_path))
    budget = create(args[0], max_trials=4, max_model_calls=8) if durable else cap()
    slots = DurableTrialSlots.create(budget, max_active=2) if durable else None
    gate = threading.Barrier(2, timeout=10)
    done = []

    def execute(_self, snapshot, _cfg, model):
        budget.reserve_trial()
        result = valid(args, snapshot, model)
        if model.plan.candidate_id != args[1]:
            gate.wait()
            done.append(model.plan.candidate_id)
            if model.plan.candidate_id == args[2][0]:
                return corrupt(result, "terminal_status")
        return result

    monkeypatch.setattr(parallel_trials.NativeDockerProbeExecutor, "execute", execute)
    monkeypatch.setattr(budget, "stop", deny_stop)
    report = run(args, budget, durable_slots=slots) if durable else run(args, budget)
    assert (
        report.stop_reason == "candidate_wave_failed" and report.budget_stop_call_succeeded is False
    )
    assert set(done) == set(args[2][:2]) and report.unstarted == args[2][2:]
    assert report.candidates[0].status == "unavailable" and report.candidates[1].status == "ok"
    assert not budget.snapshot().stopped and SECRET not in repr(report)
    if durable:
        assert slots.snapshot().occupied == 1


def test_no_stop_attempt_is_distinct_from_confirmed_stop(tmp_path, monkeypatch):
    args = setup(tmp_path)
    budget = cap()
    monkeypatch.setattr(
        parallel_trials.NativeDockerProbeExecutor,
        "execute",
        lambda _self, snapshot, _cfg, model: valid(args, snapshot, model),
    )
    ok = run(args, budget)
    assert ok.stop_reason is None and ok.budget_stop_call_succeeded is None
    monkeypatch.setattr(
        parallel_trials.NativeDockerProbeExecutor,
        "execute",
        lambda _self, snapshot, _cfg, model: corrupt(valid(args, snapshot, model), "events"),
    )
    bad = run(args, budget)
    assert bad.stop_reason == "reference_unavailable" and bad.budget_stop_call_succeeded is True
    assert budget.snapshot().stopped


def test_any_failed_stop_attempt_remains_unconfirmed_even_if_other_attempt_succeeds(
    tmp_path, monkeypatch
):
    args = three_candidates(setup(tmp_path))
    budget = cap()
    gate = threading.Barrier(2, timeout=10)
    lock = threading.Lock()
    count = 0
    original_stop = budget.stop

    def flaky_stop():
        nonlocal count
        with lock:
            count += 1
            first = count == 1
        if first:
            raise OSError(SECRET)
        original_stop()

    def execute(_self, snapshot, _cfg, model):
        result = valid(args, snapshot, model)
        if model.plan.candidate_id != args[1]:
            gate.wait()
            return corrupt(result, "events")
        return result

    monkeypatch.setattr(parallel_trials.NativeDockerProbeExecutor, "execute", execute)
    monkeypatch.setattr(budget, "stop", flaky_stop)
    report = run(args, budget)
    assert report.stop_reason == "candidate_wave_failed" and report.unstarted == args[2][2:]
    assert count == 2 and budget.snapshot().stopped
    assert report.budget_stop_call_succeeded is False and SECRET not in repr(report)


def test_scheduler_construction_failure_reports_unconfirmed_stop(tmp_path, monkeypatch):
    args = setup(tmp_path)
    budget = cap()
    seen = []

    def execute(_self, snapshot, _cfg, model):
        seen.append(model.plan.candidate_id)
        return valid(args, snapshot, model)

    def broken_pool(**_kwargs):
        raise RuntimeError("private-scheduler-error")

    monkeypatch.setattr(parallel_trials.NativeDockerProbeExecutor, "execute", execute)
    monkeypatch.setattr(parallel_trials, "ThreadPoolExecutor", broken_pool)
    monkeypatch.setattr(budget, "stop", deny_stop)
    report = run(args, budget)
    assert seen == [args[1]] and report.unstarted == args[2]
    assert (
        report.stop_reason == "scheduler_unavailable" and report.budget_stop_call_succeeded is False
    )
    assert SECRET not in repr(report) and "private-scheduler-error" not in repr(report)


def test_partial_submission_still_waits_when_stop_fails(tmp_path, monkeypatch):
    args = three_candidates(setup(tmp_path))
    budget = cap()
    started = threading.Event()
    finished = []

    def execute(_self, snapshot, _cfg, model):
        if model.plan.candidate_id != args[1]:
            started.set()
            time.sleep(0.05)
            finished.append(model.plan.candidate_id)
        return valid(args, snapshot, model)

    class BrokenPool(ThreadPoolExecutor):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.submissions = 0

        def submit(self, *a, **kw):
            self.submissions += 1
            if self.submissions == 2:
                assert started.wait(timeout=10)
                raise RuntimeError("private-scheduler-error")
            return super().submit(*a, **kw)

    monkeypatch.setattr(parallel_trials.NativeDockerProbeExecutor, "execute", execute)
    monkeypatch.setattr(parallel_trials, "ThreadPoolExecutor", BrokenPool)
    monkeypatch.setattr(budget, "stop", deny_stop)
    report = run(args, budget)
    assert (
        report.stop_reason == "scheduler_unavailable" and report.budget_stop_call_succeeded is False
    )
    assert finished == [args[2][0]] and report.unstarted == args[2][1:]
    assert SECRET not in repr(report) and "private-scheduler-error" not in repr(report)


def test_successful_return_from_stop_is_not_evidence_of_global_stop(tmp_path, monkeypatch):
    args = setup(tmp_path)
    budget = cap()
    monkeypatch.setattr(
        parallel_trials.NativeDockerProbeExecutor,
        "execute",
        lambda _self, snapshot, _cfg, model: corrupt(valid(args, snapshot, model), "events"),
    )
    monkeypatch.setattr(budget, "stop", lambda: None)
    report = run(args, budget)
    assert report.budget_stop_call_succeeded is True
    assert report.stop_reason == "reference_unavailable" and not budget.snapshot().stopped
