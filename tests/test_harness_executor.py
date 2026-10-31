"""Native executor interface and Docker-only comparison wiring; Docker mocked."""

from __future__ import annotations

import inspect

import pytest
from test_harness_comparison import provider
from test_probe_execution import Boundary
from test_probe_model import configured
from test_probe_workspace import repository

from arcen.harness import probe_container
from arcen.harness.comparison import run_reviewed_comparison
from arcen.harness.executor import NativeDockerProbeExecutor, ProbeExecutor
from arcen.harness.probe import ProbeUnavailable
from arcen.harness.probe_model import bind_probe_model
from arcen.harness.probe_workspace import snapshot_git_commit
from arcen.harness.resolver import HarnessError
from arcen.sandbox.turn import IsolationUnavailable


def bound(tmp_path):
    store, baseline, candidate, cfg = configured(tmp_path)
    repo, commit = repository(tmp_path)
    model = bind_probe_model(store, baseline, candidate, "inspect project", cfg)
    return store, baseline, candidate, cfg, repo, commit, model


def test_comparison_uses_native_executor_for_both_models_and_same_snapshot(tmp_path, monkeypatch):
    store, baseline, candidate, cfg, repo, commit, _ = bound(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    real = NativeDockerProbeExecutor.execute
    seen = []

    def capture(self, snapshot, config, model):
        seen.append((snapshot, config, model.plan.candidate_id))
        return real(self, snapshot, config, model)

    monkeypatch.setattr(NativeDockerProbeExecutor, "execute", capture)
    result = run_reviewed_comparison(
        store,
        baseline,
        candidate,
        "inspect project",
        cfg,
        lambda _: '{"winner":"tie","confidence":0.5,"reason":"equal"}',
        repo=repo,
        commit=commit,
        reviewed_inputs=True,
        reviewed_judge_inputs=True,
    )
    assert result.judgment.winner == "tie" and len(calls) == 4
    assert seen[0][0] is seen[1][0] and seen[0][1] is seen[1][1]
    assert [entry[2] for entry in seen] == [baseline, candidate]
    executor: ProbeExecutor = NativeDockerProbeExecutor()
    assert callable(executor.execute)
    assert "executor" not in inspect.signature(run_reviewed_comparison).parameters


@pytest.mark.parametrize("backend,network", [("process", "none"), ("docker", "bridge")])
def test_native_executor_rejects_unisolated_profiles_before_docker(
    tmp_path, monkeypatch, backend, network
):
    _, _, _, cfg, repo, commit, model = bound(tmp_path)
    snapshot = snapshot_git_commit(repo, commit)
    cfg.sandbox.backend, cfg.sandbox.network = backend, network
    monkeypatch.setattr(
        probe_container, "DockerTurnRegistry", lambda *a, **kw: pytest.fail("docker")
    )
    with pytest.raises(HarnessError, match="Docker with networking disabled"):
        NativeDockerProbeExecutor().execute(snapshot, cfg, model)


def test_native_executor_requires_concrete_reviewed_input_types():
    with pytest.raises(HarnessError, match="reviewed probe inputs"):
        NativeDockerProbeExecutor().execute(None, None, None)


def test_native_executor_never_falls_back_if_docker_is_unavailable(tmp_path, monkeypatch):
    _, _, _, cfg, repo, commit, model = bound(tmp_path)
    snapshot = snapshot_git_commit(repo, commit)

    def fail(*args, **kwargs):
        raise IsolationUnavailable("unavailable")

    monkeypatch.setattr(probe_container, "DockerTurnRegistry", fail)
    calls = provider(monkeypatch)
    with pytest.raises(ProbeUnavailable, match="isolation or cleanup"):
        NativeDockerProbeExecutor().execute(snapshot, cfg, model)
    assert not calls
