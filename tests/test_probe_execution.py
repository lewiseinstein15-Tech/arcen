"""Reviewed manual trial: mock provider, mocked or opt-in real Docker."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import ClassVar

import litellm
import pytest
from test_probe_model import SECRET, configured, response
from test_probe_workspace import repository

from arcen.harness import HarnessError, probe_container
from arcen.harness.probe import ProbeUnavailable
from arcen.harness.probe_execution import run_reviewed_probe
from arcen.sandbox.turn import IsolationUnavailable


class Boundary:
    instances: ClassVar[list] = []
    fail_close = False

    def __init__(self, config, *, workspace):
        self.workspace = Path(workspace)
        assert (self.workspace / "src/main.py").read_text() == "print('committed')\n"
        self.calls = []
        self.closed = False
        Boundary.instances.append(self)

    def dispatch(self, name, args):
        self.calls.append((name, dict(args)))
        return {
            "ok": True,
            "result": {
                "stdout": "tool " + SECRET + " sk-abcdefghijklmnop",
                "stderr": "",
                "exit": 0,
            },
            "error": None,
        }

    def close(self, *, strict=False):
        assert strict
        self.closed = True
        if self.fail_close:
            raise IsolationUnavailable("secret exception " + SECRET)


def scripted_provider(monkeypatch, steps):
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        return response("CODE" if len(calls) == 1 else json.dumps(steps))

    monkeypatch.setattr(litellm, "completion", completion)
    return calls


def test_reviewed_candidate_runs_through_gateway_with_scrubbed_events(tmp_path, monkeypatch):
    store, baseline, candidate, config = configured(tmp_path)
    repo, commit = repository(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = scripted_provider(
        monkeypatch, [{"title": "check", "tool": "bash", "args": {"cmd": "true", "timeout_s": 500}}]
    )
    result = run_reviewed_probe(
        store,
        baseline,
        candidate,
        "inspect project",
        config,
        repo=repo,
        commit=commit,
        reviewed_inputs=True,
    )
    assert result.status == "ok" and len(calls) == 2
    assert "CANDIDATE PLANNER" in calls[0]["messages"][0]["content"]
    assert (
        result.events[0]["type"] == "run.start"
        and result.events[0]["harness_ref"] == "sha256:" + candidate
    )
    assert result.events[-1]["type"] == "run.done" and result.events[-1]["status"] == "ok"
    assert [e["seq"] for e in result.events] == list(range(1, len(result.events) + 1))
    assert {"plan", "command", "command.done", "verify.start", "step.pass"} <= {
        e["type"] for e in result.events
    }
    assert SECRET not in repr(result.events) and "sk-abcdefghijklmnop" not in repr(result.events)
    boundary = Boundary.instances[-1]
    assert boundary.closed and not boundary.workspace.exists()
    assert len(boundary.calls) == 2 and all(args["timeout_s"] == 30 for _, args in boundary.calls)
    assert (repo / "src/main.py").read_text() == "print('committed')\n"


def test_explicit_review_required_before_any_git_or_provider(tmp_path, monkeypatch):
    store, baseline, candidate, config = configured(tmp_path)
    monkeypatch.setattr(litellm, "completion", lambda **_: pytest.fail("provider contacted"))
    with pytest.raises(HarnessError, match="explicit review"):
        run_reviewed_probe(
            store, baseline, candidate, "task", config, repo="/missing", commit="bad"
        )


def test_docker_failure_prevents_any_model_calls(tmp_path, monkeypatch):
    store, baseline, candidate, config = configured(tmp_path)
    repo, commit = repository(tmp_path)

    def unavailable(config, *, workspace):
        raise IsolationUnavailable("no Docker")

    monkeypatch.setattr(probe_container, "DockerTurnRegistry", unavailable)
    monkeypatch.setattr(litellm, "completion", lambda **_: pytest.fail("provider contacted"))
    with pytest.raises(ProbeUnavailable, match="isolation or cleanup failed"):
        run_reviewed_probe(
            store,
            baseline,
            candidate,
            "task",
            config,
            repo=repo,
            commit=commit,
            reviewed_inputs=True,
        )


@pytest.mark.parametrize("tool", ["file.read", "made-up-tool"])
def test_unsupported_tool_never_becomes_bash(tmp_path, monkeypatch, tool):
    store, baseline, candidate, config = configured(tmp_path)
    repo, commit = repository(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    scripted_provider(
        monkeypatch,
        [
            {
                "title": "unsupported",
                "tool": tool,
                "args": {"cmd": "true", "path": "/etc/passwd"},
            }
        ],
    )
    result = run_reviewed_probe(
        store, baseline, candidate, "task", config, repo=repo, commit=commit, reviewed_inputs=True
    )
    assert result.status == "failed" and not Boundary.instances[-1].calls


def test_cleanup_failure_cannot_report_success_or_leak_error(tmp_path, monkeypatch):
    store, baseline, candidate, config = configured(tmp_path)
    repo, commit = repository(tmp_path)

    class FailedCleanup(Boundary):
        fail_close = True

    monkeypatch.setattr(probe_container, "DockerTurnRegistry", FailedCleanup)
    scripted_provider(monkeypatch, [{"title": "check", "tool": "bash", "args": {"cmd": "true"}}])
    with pytest.raises(ProbeUnavailable) as error:
        run_reviewed_probe(
            store,
            baseline,
            candidate,
            "task",
            config,
            repo=repo,
            commit=commit,
            reviewed_inputs=True,
        )
    assert SECRET not in str(error.value) and Boundary.instances[-1].closed
    assert not Boundary.instances[-1].workspace.exists()


def test_real_docker_reviewed_probe_when_explicitly_enabled(tmp_path, monkeypatch):
    if os.environ.get("ARCEN_TEST_DOCKER_ISOLATION") != "1":
        pytest.skip("requires real Docker and the sandbox image")
    pytest.importorskip("docker")
    store, baseline, candidate, config = configured(tmp_path)
    repo, commit = repository(tmp_path)
    monkeypatch.setenv("ARCEN_PROBE_HOST_SECRET_MARKER", "host-only")
    command = 'test -f src/main.py && test -z "${ARCEN_PROBE_HOST_SECRET_MARKER:-}" && printf changed > src/main.py'
    scripted_provider(monkeypatch, [{"title": "check", "tool": "bash", "args": {"cmd": command}}])
    result = run_reviewed_probe(
        store,
        baseline,
        candidate,
        "edit project",
        config,
        repo=repo,
        commit=commit,
        reviewed_inputs=True,
    )
    assert result.status == "ok", result.events
    assert (repo / "src/main.py").read_text() == "print('committed')\n"


def test_direct_answer_still_uses_and_closes_isolated_container(tmp_path, monkeypatch):
    store, baseline, candidate, config = configured(tmp_path)
    repo, commit = repository(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        return response("DIRECT" if len(calls) == 1 else "A direct answer.")

    monkeypatch.setattr(litellm, "completion", completion)
    result = run_reviewed_probe(
        store, baseline, candidate, "hello", config, repo=repo, commit=commit, reviewed_inputs=True
    )
    assert result.status == "ok" and result.events[-1]["steps"] == 0
    assert Boundary.instances[-1].closed and not Boundary.instances[-1].calls


def test_provider_failure_closes_container_and_returns_generic_error(tmp_path, monkeypatch):
    store, baseline, candidate, config = configured(tmp_path)
    repo, commit = repository(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)

    def fail(**_):
        raise RuntimeError("should never leak " + SECRET)

    monkeypatch.setattr(litellm, "completion", fail)
    result = run_reviewed_probe(
        store, baseline, candidate, "task", config, repo=repo, commit=commit, reviewed_inputs=True
    )
    assert result.status == "error" and result.events[-1]["type"] == "run.error"
    assert SECRET not in repr(result.events) and Boundary.instances[-1].closed


def test_process_backend_fails_without_provider_contact(tmp_path, monkeypatch):
    store, baseline, candidate, config = configured(tmp_path)
    repo, commit = repository(tmp_path)
    config.sandbox.backend = "process"
    monkeypatch.setattr(litellm, "completion", lambda **_: pytest.fail("provider contacted"))
    with pytest.raises(ProbeUnavailable):
        run_reviewed_probe(
            store,
            baseline,
            candidate,
            "task",
            config,
            repo=repo,
            commit=commit,
            reviewed_inputs=True,
        )
