"""Persisted workspace-bound plans: opt-in Docker, mocked model and operator."""

from __future__ import annotations

import json
import os
from dataclasses import replace

import litellm
import pytest
from test_evidence_composition import completed
from test_harness_compose_test_workflow import _test_options, answer
from test_manual_cli import tty
from test_probe_execution import Boundary
from test_probe_model import response

from arcen.harness import manual_campaign, probe_container
from arcen.harness.cli import main
from arcen.harness.lineage import HarnessLineage
from arcen.sandbox.turn import DockerTurnRegistry


def exercise_later_run(tmp_path, monkeypatch, capsys, *, real_docker, mismatch):
    # Previous campaign is a disposable fixture made with a mocked Docker boundary.
    data = completed(tmp_path, monkeypatch)
    store, adopted, baseline, task_id, journal, ledger, record, previous_calls, cli = data
    budget, options = _test_options(tmp_path, data)
    config_file = tmp_path / "test-config.yaml"
    image = os.environ.get("ARCEN_H12_DOCKER_IMAGE", "arcen-h12-test:local")
    with config_file.open("a") as config:
        config.write("sandbox:\n  image: " + json.dumps(image) + "\n")
    monkeypatch.setenv("ARCEN_H12D_HOST_MARKER", "host-only-marker")
    ids, outcomes, calls, prompts = [], [], [], []

    class TrackingRegistry(DockerTurnRegistry if real_docker else Boundary):
        def __init__(self, config, *, workspace):
            super().__init__(config, workspace=workspace)
            ids.append(self._container.id if real_docker else f"mock-{len(ids)}")

        def dispatch(self, name, args):
            outcome = super().dispatch(name, args)
            outcomes.append(outcome)
            return outcome

    monkeypatch.setattr(probe_container, "DockerTurnRegistry", TrackingRegistry)

    def completion(**kwargs):
        calls.append(kwargs)
        command = (
            'test -f src/main.py && test -z "${ARCEN_H12D_HOST_MARKER:-}" '
            "&& printf changed > src/main.py"
        )
        text = (
            "CODE"
            if len(calls) % 2
            else json.dumps([{"title": "check", "tool": "bash", "args": {"cmd": command}}])
        )
        return response(text)

    monkeypatch.setattr(litellm, "completion", completion)
    tty(monkeypatch)

    def cancel_run(prompt):
        prompts.append(prompt)
        return "CANCEL" if prompt.startswith("Type RUN ") else answer(prompt)

    monkeypatch.setattr("builtins.input", cancel_run)
    assert main([*cli, *options]) == 1
    captured = capsys.readouterr()
    assert "cancelled" in captured.err
    plan_id = next(
        line.split()[4].rstrip(";")
        for line in captured.out.splitlines()
        if line.startswith("Created composite test plan:")
    )
    plan = journal.get(plan_id)
    expected = ledger.get(record.reviews[0]).workspace_sha256
    assert plan.state == "ready" and plan.workspace_sha256 == expected
    assert ids == outcomes == calls == [] and budget.snapshot().trials == 0

    # This is a second CLI invocation, not automatic resume of an interrupted run.
    assert main(["--store", str(store.root), "campaign", "status", plan_id]) == 0
    assert f"Workspace SHA-256: {expected}" in capsys.readouterr().out
    if mismatch:
        original = manual_campaign.snapshot_git_commit
        monkeypatch.setattr(
            manual_campaign,
            "snapshot_git_commit",
            lambda *args: replace(original(*args), sha256="0" * 64),
        )
    monkeypatch.setattr("builtins.input", answer)
    run_args = [
        "--store",
        str(store.root),
        "campaign",
        "run",
        plan_id,
        "--task-id",
        task_id,
        "--config",
        str(config_file),
        "--repo",
        str(tmp_path / "repo"),
        "--budget",
        budget.id,
    ]
    rc = main(run_args)
    output = capsys.readouterr().out
    usage = budget.snapshot()
    if mismatch:
        assert rc == 1 and "workspace_changed" in output
        assert journal.get(plan_id).state == "failed"
        assert ids == outcomes == calls == []
        assert (usage.trials, usage.model_calls, usage.judge_calls) == (0, 0, 0)
    else:
        assert rc == 0 and "Campaign completed" in output and "No adoption occurred" in output
        result = journal.get(plan_id)
        assert result.state == "completed" and result.baseline == baseline
        assert result.commit == record.commit and result.workspace_sha256 == expected
        assert len(result.reviews) == 1 and ledger.get(result.reviews[0]).state == "pending"
        assert len(ids) == len(set(ids)) == 2 and len(outcomes) == 4
        assert all(outcome["ok"] is True for outcome in outcomes)
        assert len(calls) == 4
        assert (usage.trials, usage.model_calls, usage.judge_calls) == (2, 4, 1)
    assert len(previous_calls) == 6
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted
    assert (tmp_path / "repo/src/main.py").read_text() == "print('committed')\n"
    return ids


@pytest.mark.parametrize("mismatch", [False, True], ids=["later-start", "snapshot-mismatch"])
def test_h12d_later_run_mocked_boundary(tmp_path, monkeypatch, capsys, mismatch):
    exercise_later_run(tmp_path, monkeypatch, capsys, real_docker=False, mismatch=mismatch)


@pytest.mark.parametrize("mismatch", [False, True], ids=["later-start", "snapshot-mismatch"])
def test_h12d_later_run_real_docker(tmp_path, monkeypatch, capsys, mismatch):
    if os.environ.get("ARCEN_TEST_DOCKER_ISOLATION") != "1":
        pytest.skip("set ARCEN_TEST_DOCKER_ISOLATION=1 to require real Docker")
    try:
        import docker
    except ImportError:
        pytest.fail("real Docker requested but Docker Python SDK is missing")
    client = docker.from_env()
    try:
        assert client.ping()
        client.images.get(os.environ.get("ARCEN_H12_DOCKER_IMAGE", "arcen-h12-test:local"))
        ids = exercise_later_run(tmp_path, monkeypatch, capsys, real_docker=True, mismatch=mismatch)
        for identifier in ids:
            with pytest.raises(docker.errors.NotFound):
                client.containers.get(identifier)
    finally:
        client.close()
