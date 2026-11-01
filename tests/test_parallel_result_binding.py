"""Parallel result attribution and conservative slot retention; all probes mocked."""

from __future__ import annotations

import threading

import pytest
from test_durable_budget import create
from test_harness_parallel_trials import cap, run, terminal, three_candidates
from test_manual_campaign import setup
from test_probe_result_binding import corrupt

from arcen.harness import parallel_trials
from arcen.harness.durable_trial_slots import DurableTrialSlots
from arcen.harness.probe_execution import ReviewedProbeResult


@pytest.mark.parametrize("durable", [False, True])
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
def test_invalid_reference_stops_and_retains_durable_slot(tmp_path, monkeypatch, durable, field):
    args = setup(tmp_path)
    budget = create(args[0]) if durable else cap()
    slots = DurableTrialSlots.create(budget, max_active=2) if durable else None
    seen = []

    def execute(_self, snapshot, _config, model):
        seen.append(model.plan.candidate_id)
        budget.reserve_trial()
        result = ReviewedProbeResult(
            args[1], model.plan.candidate_id, snapshot.commit, snapshot.sha256, "ok", terminal("ok")
        )
        return corrupt(result, field)

    monkeypatch.setattr(parallel_trials.NativeDockerProbeExecutor, "execute", execute)
    result = run(args, budget, durable_slots=slots) if durable else run(args, budget)
    assert seen == [args[1]]
    assert result.stop_reason == "reference_unavailable" and result.reference.result is None
    assert result.unstarted == args[2] and result.candidates == ()
    assert budget.snapshot().stopped and budget.snapshot().trials == 1
    if durable:
        assert slots.snapshot().occupied == 1  # uncertain result never releases slot


@pytest.mark.parametrize("durable", [False, True])
def test_bad_result_stops_later_wave_but_waits_for_inflight_peer(tmp_path, monkeypatch, durable):
    args = three_candidates(setup(tmp_path))
    budget = create(args[0], max_trials=4, max_model_calls=8) if durable else cap()
    slots = DurableTrialSlots.create(budget, max_active=2) if durable else None
    barrier = threading.Barrier(2, timeout=10)
    completed = []
    lock = threading.Lock()

    def execute(_self, snapshot, _config, model):
        identifier = model.plan.candidate_id
        budget.reserve_trial()
        result = ReviewedProbeResult(
            args[1], identifier, snapshot.commit, snapshot.sha256, "ok", terminal("ok")
        )
        if identifier != args[1]:
            barrier.wait()
            with lock:
                completed.append(identifier)
            if identifier == args[2][0]:
                return corrupt(result, "terminal_status")
        return result

    monkeypatch.setattr(parallel_trials.NativeDockerProbeExecutor, "execute", execute)
    result = run(args, budget, durable_slots=slots) if durable else run(args, budget)
    assert set(completed) == set(args[2][:2])
    assert [attempt.candidate_id for attempt in result.candidates] == list(args[2][:2])
    assert result.candidates[0].status == "unavailable" and result.candidates[0].result is None
    assert result.candidates[1].status == "ok" and result.candidates[1].result is not None
    assert result.stop_reason == "candidate_wave_failed" and result.unstarted == args[2][2:]
    assert budget.snapshot().stopped and budget.snapshot().trials == 3
    if durable:
        assert slots.snapshot().occupied == 1  # peer released, suspect slot retained
