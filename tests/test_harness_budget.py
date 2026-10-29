"""Bounded in-process shared admissions; no campaign or USD claims."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from test_harness_comparison import provider
from test_probe_execution import Boundary
from test_probe_model import configured
from test_probe_workspace import repository

from arcen.harness import HarnessError, probe_container
from arcen.harness.budget import BudgetExhausted, SharedBudget
from arcen.harness.comparison import run_reviewed_comparison
from arcen.harness.probe import ProbeUnavailable
from arcen.harness.probe_execution import run_reviewed_probe
from arcen.harness.probe_model import ProbeModelError, bind_probe_model


def budget(**changes):
    return SharedBudget(
        **(
            {"max_trials": 2, "max_model_calls": 4, "max_judge_calls": 1, "admission_seconds": 60}
            | changes
        )
    )


@pytest.mark.parametrize(
    "values",
    [
        {"max_trials": True},
        {"max_trials": 0},
        {"max_trials": -1},
        {"max_model_calls": 1.2},
        {"max_judge_calls": -1},
        {"max_judge_calls": 100001},
        {"admission_seconds": True},
        {"admission_seconds": float("nan")},
        {"admission_seconds": 0},
        {"admission_seconds": float("inf")},
    ],
)
def test_invalid_limits_rejected(values):
    with pytest.raises(HarnessError, match="limits"):
        budget(**values)


def test_atomic_concurrent_reservations_and_latched_exhaustion():
    shared = budget(max_model_calls=7)

    def reserve(_):
        try:
            shared.reserve_model_call()
            return True
        except BudgetExhausted:
            return False

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(reserve, range(100)))
    assert sum(results) == 7
    snap = shared.snapshot()
    assert snap.model_calls == 7 and snap.stopped and snap.reason == "model_calls limit reached"
    with pytest.raises(BudgetExhausted):
        shared.reserve_trial()
    with pytest.raises(BudgetExhausted):
        shared.reserve_judge_call()


def test_stop_and_monotonic_admission_cutoff(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("arcen.harness.budget.time.monotonic", lambda: now[0])
    shared = budget(admission_seconds=2)
    shared.reserve_trial()
    now[0] = 101.99
    shared.checkpoint()
    now[0] = 102.0
    with pytest.raises(BudgetExhausted, match="deadline"):
        shared.reserve_model_call()
    now[0] = 90  # closure remains latched even if a clock source misbehaves
    assert shared.snapshot().reason == "admission deadline reached"
    other = budget()
    other.stop()
    with pytest.raises(BudgetExhausted, match="stopped"):
        other.checkpoint()


def test_pair_shares_trial_model_and_judge_limits(tmp_path, monkeypatch):
    store, baseline, candidate, cfg = configured(tmp_path)
    repo, commit = repository(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    judged = []
    shared = budget()
    result = run_reviewed_comparison(
        store,
        baseline,
        candidate,
        "task",
        cfg,
        lambda data: judged.append(data) or '{"winner":"tie","confidence":0.5,"reason":"equal"}',
        repo=repo,
        commit=commit,
        reviewed_inputs=True,
        reviewed_judge_inputs=True,
        budget=shared,
    )
    assert result.judgment.winner == "tie" and len(calls) == 4 and len(judged) == 1
    snap = shared.snapshot()
    assert (snap.trials, snap.model_calls, snap.judge_calls, snap.stopped) == (2, 4, 1, False)
    with pytest.raises(BudgetExhausted, match="trials"):
        run_reviewed_probe(
            store,
            baseline,
            candidate,
            "task",
            cfg,
            repo=repo,
            commit=commit,
            reviewed_inputs=True,
            budget=shared,
        )
    assert len(calls) == 4


def test_model_exhaustion_stops_future_trials_and_judge(tmp_path, monkeypatch):
    store, baseline, candidate, cfg = configured(tmp_path)
    repo, commit = repository(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    shared = budget(max_model_calls=3)

    def judge(_):
        pytest.fail("judge must not be called")

    try:
        result = run_reviewed_comparison(
            store,
            baseline,
            candidate,
            "task",
            cfg,
            judge,
            repo=repo,
            commit=commit,
            reviewed_inputs=True,
            reviewed_judge_inputs=True,
            budget=shared,
        )
    except (BudgetExhausted, ProbeUnavailable):
        pass
    else:
        assert result.judgment is None
    assert len(calls) == 3 and shared.snapshot().model_calls == 3
    assert shared.snapshot().stopped and all(x.closed for x in Boundary.instances[-2:])


def test_judge_budget_blocks_callback_and_does_not_exceed_reservation(tmp_path, monkeypatch):
    store, baseline, candidate, cfg = configured(tmp_path)
    repo, commit = repository(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    shared = budget(max_judge_calls=0)
    with pytest.raises(ProbeUnavailable, match="judge failed"):
        run_reviewed_comparison(
            store,
            baseline,
            candidate,
            "task",
            cfg,
            lambda _: pytest.fail("judge called"),
            repo=repo,
            commit=commit,
            reviewed_inputs=True,
            reviewed_judge_inputs=True,
            budget=shared,
        )
    assert len(calls) == 4
    assert shared.snapshot().judge_calls == 0 and shared.snapshot().stopped


def test_stop_during_provider_blocks_new_tool_dispatch(tmp_path, monkeypatch):
    store, baseline, candidate, cfg = configured(tmp_path)
    repo, commit = repository(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    shared = budget()
    calls = provider(monkeypatch, hook=lambda n: shared.stop() if n == 2 else None)
    try:
        run_reviewed_comparison(
            store,
            baseline,
            candidate,
            "task",
            cfg,
            lambda _: pytest.fail("judge called"),
            repo=repo,
            commit=commit,
            reviewed_inputs=True,
            reviewed_judge_inputs=True,
            budget=shared,
        )
    except (BudgetExhausted, ProbeUnavailable):
        pass
    assert len(calls) == 2 and Boundary.instances[-1].calls == []
    assert Boundary.instances[-1].closed and shared.snapshot().stopped


def test_failed_provider_call_consumed_and_shared_across_bound_models(tmp_path, monkeypatch):
    store, baseline, candidate, cfg = configured(tmp_path)
    calls = provider(monkeypatch, fail_at=1)
    shared = budget(max_model_calls=1)
    one = bind_probe_model(store, baseline, baseline, "task", cfg, budget=shared)
    two = bind_probe_model(store, baseline, candidate, "task", cfg, budget=shared)
    messages = [{"role": "user", "content": "task"}]
    with pytest.raises(ProbeModelError):
        one.complete("planner", messages)
    with pytest.raises(ProbeModelError, match="budget"):
        two.complete("planner", messages)
    assert len(calls) == 1 and shared.snapshot().model_calls == 1


def test_invalid_budget_rejected_before_snapshot_or_provider(tmp_path, monkeypatch):
    store, baseline, candidate, cfg = configured(tmp_path)
    monkeypatch.setattr(
        "arcen.harness.comparison.snapshot_git_commit", lambda *a: pytest.fail("snapshot")
    )
    with pytest.raises(HarnessError, match="budget"):
        run_reviewed_comparison(
            store,
            baseline,
            candidate,
            "task",
            cfg,
            lambda _: "",
            repo="/missing",
            commit="invalid",
            reviewed_inputs=True,
            reviewed_judge_inputs=True,
            budget=object(),
        )


def test_composition_forwards_the_same_budget(tmp_path, monkeypatch):
    from test_harness_composer import proposal

    from arcen.harness.proposal_comparison import compare_reviewed_proposals

    store, baseline, _, cfg = configured(tmp_path)
    repo, commit = repository(tmp_path)
    path = "prompts/forge.md"
    raw = store.get_blob(store.get_manifest(baseline).components[path])
    p = proposal(store, baseline, path, raw + b"extra\n")
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    provider(monkeypatch)
    shared = budget()
    result = compare_reviewed_proposals(
        store,
        baseline,
        (p,),
        "task",
        cfg,
        lambda _: '{"winner":"tie","confidence":0.5,"reason":"equal"}',
        repo=repo,
        commit=commit,
        reviewed_inputs=True,
        reviewed_judge_inputs=True,
        budget=shared,
    )
    assert result.comparison.judgment.winner == "tie"
    snap = shared.snapshot()
    assert (snap.trials, snap.model_calls, snap.judge_calls) == (2, 4, 1)


def test_real_docker_shared_budget_pair_when_explicitly_enabled(tmp_path, monkeypatch):
    import os

    if os.environ.get("ARCEN_TEST_DOCKER_ISOLATION") != "1":
        pytest.skip("requires real Docker and the sandbox image")
    pytest.importorskip("docker")
    store, baseline, candidate, cfg = configured(tmp_path)
    repo, commit = repository(tmp_path)
    provider(monkeypatch)
    shared = budget()
    result = run_reviewed_comparison(
        store,
        baseline,
        candidate,
        "task",
        cfg,
        lambda _: '{"winner":"tie","confidence":0.5,"reason":"equal"}',
        repo=repo,
        commit=commit,
        reviewed_inputs=True,
        reviewed_judge_inputs=True,
        budget=shared,
    )
    assert result.reference.status == result.candidate.status == "ok"
    assert result.judgment.winner == "tie"
    snap = shared.snapshot()
    assert (snap.trials, snap.model_calls, snap.judge_calls) == (2, 4, 1)
