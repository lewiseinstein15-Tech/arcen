"""H-12c compose-to-test smoke: opt-in real Docker, mocked model and operator."""

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


def exercise(tmp_path, monkeypatch, capsys, *, real_docker, mismatch=False):
    # Earlier recorded reviews are intentionally produced using the mocked boundary.
    data = completed(tmp_path, monkeypatch)
    store, adopted, baseline, _, journal, ledger, record, previous_calls, cli = data
    budget, options = _test_options(tmp_path, data)
    image = os.environ.get("ARCEN_H12_DOCKER_IMAGE", "arcen-h12-test:local")
    with (tmp_path / "test-config.yaml").open("a") as config:
        config.write("sandbox:\n  image: " + json.dumps(image) + "\n")
    monkeypatch.setenv("ARCEN_H12C_HOST_MARKER", "host-only-marker")
    ids, outcomes, calls, confirmations = [], [], [], []

    class TrackingRegistry(DockerTurnRegistry if real_docker else Boundary):
        def __init__(self, config, *, workspace):
            super().__init__(config, workspace=workspace)
            ids.append(self._container.id if real_docker else f"mock-{len(ids)}")

        def dispatch(self, name, args):
            result = super().dispatch(name, args)
            outcomes.append(result)
            return result

    monkeypatch.setattr(probe_container, "DockerTurnRegistry", TrackingRegistry)

    def completion(**kwargs):
        calls.append(kwargs)
        command = (
            'test -f src/main.py && test -z "${ARCEN_H12C_HOST_MARKER:-}" '
            "&& printf changed > src/main.py"
        )
        content = (
            "CODE"
            if len(calls) % 2
            else json.dumps([{"title": "check", "tool": "bash", "args": {"cmd": command}}])
        )
        return response(content)

    monkeypatch.setattr(litellm, "completion", completion)
    tty(monkeypatch)

    def confirm(prompt):
        confirmations.append(prompt.split()[1].rstrip(","))
        return answer(prompt)

    monkeypatch.setattr("builtins.input", confirm)
    if mismatch:
        original = manual_campaign.snapshot_git_commit
        monkeypatch.setattr(
            manual_campaign,
            "snapshot_git_commit",
            lambda *args: replace(original(*args), sha256="0" * 64),
        )
    rc = main([*cli, *options])
    output = capsys.readouterr().out
    plan_id = next(
        line.split()[4].rstrip(";")
        for line in output.splitlines()
        if line.startswith("Created composite test plan:")
    )
    plan = journal.get(plan_id)
    assert confirmations[:3] == ["COMPOSE", "PLAN", "RUN"]
    assert "Required workspace SHA-256" in output and "bound to the plan" in output
    assert len(previous_calls) == 6
    usage = budget.snapshot()
    if mismatch:
        assert rc == 1 and "workspace_changed" in output and plan.state == "failed"
        assert ids == outcomes == calls == []
        assert (usage.trials, usage.model_calls, usage.judge_calls) == (0, 0, 0)
    else:
        assert rc == 0 and "Campaign completed" in output and "No adoption occurred" in output
        assert plan.state == "completed" and len(plan.candidates) == len(plan.reviews) == 1
        assert plan.baseline == baseline and plan.commit == record.commit
        assert ledger.get(plan.reviews[0]).state == "pending"
        # Forge executes each command once and Temper verifies it by rerunning it.
        assert len(ids) == len(set(ids)) == 2 and len(outcomes) == 4
        assert all(item["ok"] is True for item in outcomes)
        assert len(calls) == 4 and confirmations[-1] == "A"
        assert (usage.trials, usage.model_calls, usage.judge_calls) == (2, 4, 1)
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted
    assert (tmp_path / "repo/src/main.py").read_text() == "print('committed')\n"
    return ids


@pytest.mark.parametrize("mismatch", [False, True], ids=["confirmed-test", "snapshot-mismatch"])
def test_h12c_flow_with_mocked_docker(tmp_path, monkeypatch, capsys, mismatch):
    exercise(tmp_path, monkeypatch, capsys, real_docker=False, mismatch=mismatch)


@pytest.mark.parametrize("mismatch", [False, True], ids=["confirmed-test", "snapshot-mismatch"])
def test_h12c_flow_with_real_docker(tmp_path, monkeypatch, capsys, mismatch):
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
        ids = exercise(tmp_path, monkeypatch, capsys, real_docker=True, mismatch=mismatch)
        for identifier in ids:
            with pytest.raises(docker.errors.NotFound):
                client.containers.get(identifier)
    finally:
        client.close()
