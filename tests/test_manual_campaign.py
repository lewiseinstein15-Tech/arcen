"""Manually initiated sequential comparisons; mocks unless explicitly marked."""

from __future__ import annotations

import json
import os

import pytest
from test_harness_comparison import provider
from test_harness_probe import changed
from test_probe_execution import Boundary
from test_probe_model import SECRET, configured
from test_probe_workspace import repository

from arcen.harness import HarnessError, probe_container
from arcen.harness import manual_campaign as module
from arcen.harness.budget import SharedBudget
from arcen.harness.manual_campaign import run_manual_campaign
from arcen.harness.review import ReviewLedger


def setup(tmp_path):
    store, baseline, candidate1, cfg = configured(tmp_path)
    base = store.get_manifest(baseline)
    path = "prompts/forge.md"
    candidate2 = changed(
        store, base, path, store.get_blob(base.components[path]) + b"review checks\n"
    )
    repo, commit = repository(tmp_path)
    reviews = ReviewLedger(store, create=True)
    return store, baseline, (candidate1, candidate2), cfg, repo, commit, reviews


def budget(**changes):
    return SharedBudget(
        **(
            {"max_trials": 3, "max_model_calls": 6, "max_judge_calls": 2, "admission_seconds": 60}
            | changes
        )
    )


def judge(_):
    return '{"winner":"tie","confidence":0.5,"reason":"no clear difference"}'


def run(args, **changes):
    store, baseline, candidates, cfg, repo, commit, reviews = args
    options = {
        "repo": repo,
        "commit": commit,
        "reviews": reviews,
        "budget": budget(),
        "reviewed_inputs": True,
        "reviewed_judge_inputs": True,
    }
    options.update(changes)
    return run_manual_campaign(
        store, baseline, candidates, "inspect project", cfg, judge, **options
    )


def test_same_snapshot_reference_reused_and_pending_reviews_only(tmp_path, monkeypatch):
    args = setup(tmp_path)
    store, baseline, candidates, cfg, repo, commit, reviews = args
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    original = module.snapshot_git_commit
    captures = []

    def snapshot(*a):
        value = original(*a)
        captures.append(value.sha256)
        return value

    monkeypatch.setattr(module, "snapshot_git_commit", snapshot)

    def mutate(n):
        if n == 1:
            (repo / "src/main.py").write_text("host changed\n")
            cfg.provider.model = "mutated"

    calls = provider(monkeypatch, hook=mutate)
    selected_budget = budget()
    result = run(args, budget=selected_budget)
    assert result.stop_reason is None and result.stopped_candidate is None
    assert [item.candidate_id for item in result.completed] == list(candidates)
    assert len(captures) == 1 and len(calls) == 6
    assert all(call["model"] == "openai/mock-model" for call in calls)
    assert all(item.comparison.reference is result.reference for item in result.completed)
    assert all(
        item.comparison.candidate.workspace_sha256
        == result.reference.workspace_sha256
        == captures[0]
        for item in result.completed
    )
    assert all(
        item.comparison.candidate.commit == commit and item.review.state == "pending"
        for item in result.completed
    )
    assert len(reviews.list()) == 2 and all(x.source == "paired" for x in reviews.list())
    boundaries = Boundary.instances[-3:]
    assert len({id(x) for x in boundaries}) == 3 and all(
        x.closed and not x.workspace.exists() for x in boundaries
    )
    snap = selected_budget.snapshot()
    assert (snap.trials, snap.model_calls, snap.judge_calls) == (3, 6, 2)
    assert not (store.root / "lineage.sqlite3").exists()
    assert (repo / "src/main.py").read_text() == "host changed\n"
    assert (
        baseline not in repr(result.reference.events) or result.reference.events[0]["harness_ref"]
    )


def test_validation_preflight_before_git_provider_and_writes(tmp_path, monkeypatch):
    args = setup(tmp_path)
    store, baseline, candidates, cfg, _, _, reviews = args
    monkeypatch.setattr(module, "snapshot_git_commit", lambda *_: pytest.fail("git called"))
    monkeypatch.setattr(
        probe_container, "DockerTurnRegistry", lambda *a, **k: pytest.fail("docker called")
    )
    common = {
        "repo": "/bad",
        "commit": "bad",
        "reviews": reviews,
        "budget": budget(),
        "reviewed_inputs": True,
        "reviewed_judge_inputs": True,
    }
    for pair in (
        (),
        (baseline,),
        (candidates[0], candidates[0]),
        (candidates[0], "0" * 64),
        (candidates[0],) * 6,
    ):
        with pytest.raises(HarnessError):
            run_manual_campaign(store, baseline, pair, "task", cfg, judge, **common)
    with pytest.raises(HarnessError):
        run_manual_campaign(
            store, baseline, candidates, "task", cfg, judge, **(common | {"budget": None})
        )
    with pytest.raises(HarnessError):
        run_manual_campaign(
            store, baseline, candidates, "task", cfg, judge, **(common | {"reviewed_inputs": False})
        )
    with pytest.raises(HarnessError):
        run_manual_campaign(
            store,
            baseline,
            candidates,
            "task",
            cfg,
            judge,
            **(common | {"reviewed_judge_inputs": False}),
        )
    assert reviews.list() == ()


def test_provider_failure_keeps_prior_pending_review_and_stops(tmp_path, monkeypatch):
    args = setup(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch, fail_at=5)
    result = run(args)
    assert result.stop_reason == "candidate_failed" and result.stopped_candidate == args[2][1]
    assert len(result.completed) == 1 and len(args[-1].list()) == 1
    assert len(calls) == 5 and SECRET not in repr(result)
    assert all(b.closed for b in Boundary.instances[-3:])


def test_judge_failure_stops_and_does_not_leak_exception(tmp_path, monkeypatch):
    args = setup(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    judge_calls = []

    def failing_judge(request):
        judge_calls.append(request)
        if len(judge_calls) == 2:
            raise ValueError(SECRET)
        return judge(request)

    store, baseline, candidates, cfg, repo, commit, reviews = args
    result = run_manual_campaign(
        store,
        baseline,
        candidates,
        "task",
        cfg,
        failing_judge,
        repo=repo,
        commit=commit,
        reviews=reviews,
        budget=budget(),
        reviewed_inputs=True,
        reviewed_judge_inputs=True,
    )
    assert result.stop_reason == "judge_failed" and len(result.completed) == 1
    assert len(calls) == 6 and len(reviews.list()) == 1 and SECRET not in repr(result)


def test_shared_budget_stops_before_next_trial(tmp_path, monkeypatch):
    args = setup(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    cap = budget(max_trials=2)
    result = run(args, budget=cap)
    assert result.stop_reason == "budget_closed" and result.stopped_candidate == args[2][1]
    assert len(result.completed) == 1 and len(calls) == 4 and len(args[-1].list()) == 1
    assert cap.snapshot().trials == 2 and cap.snapshot().stopped


def test_stop_during_judge_prevents_record_and_future_candidates(tmp_path, monkeypatch):
    args = setup(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    cap = budget()

    def stopping_judge(request):
        cap.stop()
        return judge(request)

    store, baseline, candidates, cfg, repo, commit, reviews = args
    result = run_manual_campaign(
        store,
        baseline,
        candidates,
        "task",
        cfg,
        stopping_judge,
        repo=repo,
        commit=commit,
        reviews=reviews,
        budget=cap,
        reviewed_inputs=True,
        reviewed_judge_inputs=True,
    )
    assert result.stop_reason == "budget_closed" and not result.completed
    assert len(calls) == 4 and reviews.list() == ()


def test_ledger_failure_stops_after_first_candidate(tmp_path, monkeypatch):
    args = setup(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)

    def fail(_):
        raise ValueError("private information " + SECRET)

    monkeypatch.setattr(args[-1], "request_from_comparison", fail)
    result = run(args)
    assert result.stop_reason == "review_record_failed" and not result.completed
    assert len(calls) == 4 and SECRET not in repr(result)


def test_real_docker_manual_campaign_when_explicitly_enabled(tmp_path, monkeypatch):
    if os.environ.get("ARCEN_TEST_DOCKER_ISOLATION") != "1":
        pytest.skip("requires real Docker and sandbox image")
    pytest.importorskip("docker")
    args = setup(tmp_path)
    provider(monkeypatch)
    result = run(args)
    assert result.stop_reason is None and len(result.completed) == 2
    assert all(item.review.state == "pending" for item in result.completed)


def test_reference_failure_stops_before_candidates_and_judge(tmp_path, monkeypatch):
    args = setup(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch, fail_at=1)
    result = run(args)
    assert result.stop_reason == "reference_failed" and not result.completed
    assert len(calls) == 1 and args[-1].list() == () and Boundary.instances[-1].closed


def test_isolation_cleanup_failure_stops_without_results(tmp_path, monkeypatch):
    args = setup(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    monkeypatch.setattr(Boundary, "fail_close", True)
    provider(monkeypatch)
    result = run(args)
    assert result.stop_reason == "reference_isolation_failed" and not result.completed
    assert args[-1].list() == ()


def test_existing_pending_review_refuses_duplicate_after_trial(tmp_path, monkeypatch):
    from test_harness_review import pair_for

    args = setup(tmp_path)
    args[-1].request_from_comparison(pair_for(args[1], args[2][0]))
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    result = run(args)
    assert result.stop_reason == "review_record_failed" and not result.completed
    assert len(calls) == 4 and len(args[-1].list()) == 1


def test_each_judge_request_is_reduced_and_blinded(tmp_path, monkeypatch):
    args = setup(tmp_path)
    store, baseline, candidates, cfg, repo, commit, reviews = args
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    provider(monkeypatch)
    seen = []

    def checking(request):
        seen.append(request)
        raw = json.dumps(request)
        assert baseline not in raw and candidates[len(seen) - 1] not in raw
        assert SECRET not in raw and "CANDIDATE PLANNER" not in raw
        assert set(request) == {"task", "trajectory_a", "trajectory_b", "instructions"}
        return judge(request)

    result = run_manual_campaign(
        store,
        baseline,
        candidates,
        "task",
        cfg,
        checking,
        repo=repo,
        commit=commit,
        reviews=reviews,
        budget=budget(),
        reviewed_inputs=True,
        reviewed_judge_inputs=True,
    )
    assert result.stop_reason is None and len(seen) == 2
