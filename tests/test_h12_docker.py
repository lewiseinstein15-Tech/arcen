"""H-12 composed candidate comparison: mocked locally, opt-in real Docker."""

from __future__ import annotations

import json
import os

import litellm
import pytest
from test_harness_composer import proposal
from test_probe_execution import Boundary
from test_probe_model import configured, response
from test_probe_workspace import repository

from arcen.harness import probe_container
from arcen.harness.budget import SharedBudget
from arcen.harness.proposal_comparison import compare_reviewed_proposals
from arcen.sandbox.turn import DockerTurnRegistry


def exercise_composite(tmp_path, monkeypatch, *, real_docker):
    store, baseline, _, cfg = configured(tmp_path)
    base = store.get_manifest(baseline)
    repo, commit = repository(tmp_path)
    paths = ("prompts/draft.md", "tool-guidance.md")
    proposals = tuple(
        proposal(
            store, baseline, path, store.get_blob(base.components[path]) + b"Review outputs.\n"
        )
        for path in paths
    )
    monkeypatch.setenv("ARCEN_H12_HOST_SECRET_MARKER", "h12-host-only-secret-value")
    calls, judged, ids = [], [], []

    def completion(**kwargs):
        calls.append(kwargs)
        command = 'test -f src/main.py && test -z "${ARCEN_H12_HOST_SECRET_MARKER:-}"'
        text = (
            "CODE"
            if len(calls) % 2
            else json.dumps([{"title": "check", "tool": "bash", "args": {"cmd": command}}])
        )
        return response(text)

    def judge(request):
        judged.append(request)
        assert baseline not in json.dumps(request)
        return '{"winner":"tie","confidence":0.5,"reason":"mocked judgment"}'

    monkeypatch.setattr(litellm, "completion", completion)
    if real_docker:
        import docker

        cfg.sandbox.image = os.environ.get("ARCEN_H12_DOCKER_IMAGE", cfg.sandbox.image)
        client = docker.from_env()
        try:
            assert client.ping()

            class TrackingRegistry(DockerTurnRegistry):
                def __init__(self, config, *, workspace):
                    super().__init__(config, workspace=workspace)
                    ids.append(self._container.id)

            monkeypatch.setattr(probe_container, "DockerTurnRegistry", TrackingRegistry)
            run_composite(
                store, baseline, proposals, cfg, repo, commit, calls, judged, judge, paths
            )
            assert len(ids) == len(set(ids)) == 2
            for identifier in ids:
                with pytest.raises(docker.errors.NotFound):
                    client.containers.get(identifier)
        finally:
            client.close()
    else:
        monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
        run_composite(store, baseline, proposals, cfg, repo, commit, calls, judged, judge, paths)
    assert (repo / "src/main.py").read_text() == "print('committed')\n"
    assert not (store.root / "lineage.sqlite3").exists()


def run_composite(store, baseline, proposals, cfg, repo, commit, calls, judged, judge, paths):
    budget = SharedBudget(max_trials=2, max_model_calls=4, max_judge_calls=1, admission_seconds=300)
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
        budget=budget,
    )
    assert result.composition.candidate_id and not result.composition.conflicts
    assert result.composition.changed_paths == tuple(sorted(paths))
    composite = store.get_manifest(result.composition.candidate_id)
    for item in proposals:
        assert store.get_blob(composite.components[item.path]) == item.after
    pair = result.comparison
    assert pair.reference.status == pair.candidate.status == "ok"
    assert pair.candidate.candidate_id == result.composition.candidate_id
    assert pair.reference.workspace_sha256 == pair.candidate.workspace_sha256
    assert pair.reference.commit == pair.candidate.commit == commit
    assert pair.judgment.winner == "tie" and len(calls) == 4 and len(judged) == 1
    snap = budget.snapshot()
    assert (snap.trials, snap.model_calls, snap.judge_calls) == (2, 4, 1)


def test_h12_composite_flow_with_mocked_docker(tmp_path, monkeypatch):
    exercise_composite(tmp_path, monkeypatch, real_docker=False)


def test_h12_composite_flow_with_real_docker(tmp_path, monkeypatch):
    if os.environ.get("ARCEN_TEST_DOCKER_ISOLATION") != "1":
        pytest.skip("set ARCEN_TEST_DOCKER_ISOLATION=1 to require real Docker")
    try:
        import docker  # noqa: F401
    except ImportError:
        pytest.fail("real Docker test requested but the Docker Python SDK is missing")
    exercise_composite(tmp_path, monkeypatch, real_docker=True)
