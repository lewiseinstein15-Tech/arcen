"""Same-snapshot reviewed comparison and blinded judge; Docker is mocked."""

from __future__ import annotations

import json
import os

import litellm
import pytest
from test_probe_execution import Boundary
from test_probe_model import SECRET, configured, response
from test_probe_workspace import repository

from arcen.harness import HarnessError, probe_container
from arcen.harness import comparison as module
from arcen.harness.comparison import run_reviewed_comparison
from arcen.harness.probe import ProbeUnavailable


def provider(monkeypatch, *, fail_at=None, hook=None):
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        if hook:
            hook(len(calls))
        if len(calls) == fail_at:
            raise RuntimeError("provider failure " + SECRET)
        text = (
            "CODE"
            if len(calls) % 2
            else json.dumps([{"title": "check", "tool": "bash", "args": {"cmd": "true"}}])
        )
        return response(text)

    monkeypatch.setattr(litellm, "completion", completion)
    return calls


def test_pair_uses_one_snapshot_independent_containers_and_blinded_judge(tmp_path, monkeypatch):
    store, baseline, candidate, cfg = configured(tmp_path)
    repo, commit = repository(tmp_path)
    cfg.provider.api_key = "$PAIR_KEY"
    monkeypatch.setenv("PAIR_KEY", SECRET)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    original_snapshot = module.snapshot_git_commit
    snapshots = []

    def capture(repo_path, commit_id):
        value = original_snapshot(repo_path, commit_id)
        snapshots.append(value.sha256)
        return value

    monkeypatch.setattr(module, "snapshot_git_commit", capture)

    def mutate_after_first_call(number):
        if number == 1:
            (repo / "src/main.py").write_text("modified on host\n")
            cfg.provider.model = "changed"
            monkeypatch.setenv("PAIR_KEY", "new-secret-should-not-be-used")

    calls = provider(monkeypatch, hook=mutate_after_first_call)

    def judge(request):
        raw = json.dumps(request)
        assert baseline not in raw and candidate not in raw and SECRET not in raw
        assert "CANDIDATE PLANNER" not in raw
        assert set(request) == {"task", "trajectory_a", "trajectory_b", "instructions"}
        return '{"winner":"tie","confidence":0.7,"reason":"no clear difference"}'

    result = run_reviewed_comparison(
        store,
        baseline,
        candidate,
        "inspect project",
        cfg,
        judge,
        repo=repo,
        commit=commit,
        reviewed_inputs=True,
        reviewed_judge_inputs=True,
    )
    assert result.judgment.winner == "tie"
    assert result.reference.status == result.candidate.status == "ok"
    assert len(snapshots) == 1
    assert result.reference.workspace_sha256 == result.candidate.workspace_sha256 == snapshots[0]
    assert result.reference.commit == result.candidate.commit == commit
    first, second = Boundary.instances[-2:]
    assert first is not second and first.closed and second.closed
    assert (
        first.workspace != second.workspace
        and not first.workspace.exists()
        and not second.workspace.exists()
    )
    assert len(calls) == 4 and all(
        call["model"] == "openai/mock-model" and call["api_key"] == SECRET for call in calls
    )
    assert "CANDIDATE PLANNER" not in calls[0]["messages"][0]["content"]
    assert "CANDIDATE PLANNER" in calls[2]["messages"][0]["content"]
    assert (repo / "src/main.py").read_text() == "modified on host\n"


def test_review_gates_and_candidate_preflight_run_before_provider_or_git(tmp_path, monkeypatch):
    store, baseline, candidate, cfg = configured(tmp_path)
    monkeypatch.setattr(module, "snapshot_git_commit", lambda *a: pytest.fail("git called"))
    monkeypatch.setattr(litellm, "completion", lambda **kw: pytest.fail("provider called"))
    for review_inputs, review_judge in ((False, False), (True, False), (False, True)):
        with pytest.raises(HarnessError, match="explicit review"):
            run_reviewed_comparison(
                store,
                baseline,
                candidate,
                "task",
                cfg,
                lambda _: "",
                repo="/missing",
                commit="bad",
                reviewed_inputs=review_inputs,
                reviewed_judge_inputs=review_judge,
            )
    with pytest.raises(HarnessError, match="distinct"):
        run_reviewed_comparison(
            store,
            baseline,
            baseline,
            "task",
            cfg,
            lambda _: "",
            repo="/missing",
            commit="bad",
            reviewed_inputs=True,
            reviewed_judge_inputs=True,
        )
    with pytest.raises(HarnessError):
        run_reviewed_comparison(
            store,
            baseline,
            "0" * 64,
            "task",
            cfg,
            lambda _: "",
            repo="/missing",
            commit="bad",
            reviewed_inputs=True,
            reviewed_judge_inputs=True,
        )


def test_reference_provider_error_stops_without_candidate_or_judge(tmp_path, monkeypatch):
    store, baseline, candidate, cfg = configured(tmp_path)
    repo, commit = repository(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch, fail_at=1)
    result = run_reviewed_comparison(
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
    )
    assert (
        result.reference.status == "error" and result.candidate is None and result.judgment is None
    )
    assert len(calls) == 1 and Boundary.instances[-1].closed


def test_candidate_provider_error_stops_before_judge(tmp_path, monkeypatch):
    store, baseline, candidate, cfg = configured(tmp_path)
    repo, commit = repository(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch, fail_at=3)
    result = run_reviewed_comparison(
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
    )
    assert (
        result.reference.status == "ok"
        and result.candidate.status == "error"
        and result.judgment is None
    )
    assert len(calls) == 3


def test_judge_failure_does_not_leak_exception_or_produce_verdict(tmp_path, monkeypatch):
    store, baseline, candidate, cfg = configured(tmp_path)
    repo, commit = repository(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    provider(monkeypatch)

    def judge(_):
        raise RuntimeError(SECRET)

    with pytest.raises(ProbeUnavailable, match="judge failed") as exc:
        run_reviewed_comparison(
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
        )
    assert SECRET not in str(exc.value)
    assert all(x.closed for x in Boundary.instances[-2:])


def test_real_docker_paired_comparison_when_explicitly_enabled(tmp_path, monkeypatch):
    if os.environ.get("ARCEN_TEST_DOCKER_ISOLATION") != "1":
        pytest.skip("requires real Docker and the sandbox image")
    pytest.importorskip("docker")
    store, baseline, candidate, cfg = configured(tmp_path)
    repo, commit = repository(tmp_path)
    provider(monkeypatch)
    result = run_reviewed_comparison(
        store,
        baseline,
        candidate,
        "task",
        cfg,
        lambda _: '{"winner":"tie","confidence":0.5,"reason":"same"}',
        repo=repo,
        commit=commit,
        reviewed_inputs=True,
        reviewed_judge_inputs=True,
    )
    assert result.reference.status == result.candidate.status == "ok"
    assert result.reference.workspace_sha256 == result.candidate.workspace_sha256
    assert result.judgment.winner == "tie"
