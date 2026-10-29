"""H-01: the headless surface uses the shared turn and fails closed."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fake_turn_registry import FakeTurnRegistry

from arcen.config import ArcenConfig
from arcen.headless import execute
from arcen.llm.client import LLMResponse, ProviderError
from arcen.server.app import ServerState


class Planner:
    def is_available(self):
        return True

    def complete(self, role, messages, **kwargs):
        if "Return ONLY the word" in messages[-1]["content"]:
            return LLMResponse(text="CODE", model="mock", tokens={"input": 1, "output": 1})
        return LLMResponse(
            text=json.dumps([{"title": "do the task", "tool": "bash", "args": {"cmd": "true"}}]),
            model="mock",
            tokens={"input": 1, "output": 1},
        )


def make_state(tmp_path, llm=None):
    config = ArcenConfig()
    config.session.dir = str(tmp_path / "sessions")
    state = ServerState(config)
    state.llm = llm
    return state


def test_shared_turn_envelope_and_schema(monkeypatch, tmp_path):
    import jsonschema

    from arcen.server import app

    fake = FakeTurnRegistry()
    monkeypatch.setattr(app, "create_turn_registry", lambda config: fake)
    result = execute("run the task", state=make_state(tmp_path, Planner()))
    schema = json.loads(
        (Path(__file__).parents[1] / "docs/headless-result.schema.json").read_text()
    )
    jsonschema.validate(result, schema)
    assert result["status"] == "ok" and fake.closed
    types = [e["type"] for e in result["events"]]
    assert {"run.start", "plan", "command", "verify.start", "run.done"} <= set(types)
    assert len(fake.calls) >= 2  # FORGE and TEMPER share the injected boundary.


def test_run_error_is_nonzero_status(monkeypatch, tmp_path):
    from arcen.sandbox.turn import IsolationUnavailable
    from arcen.server import app

    def unavailable(config):
        raise IsolationUnavailable("Docker unavailable")

    monkeypatch.setattr(app, "create_turn_registry", unavailable)
    result = execute("run the task", state=make_state(tmp_path, Planner()))
    assert result["status"] == "error"
    assert result["error"]["code"] == "SANDBOX_UNAVAILABLE"
    assert not any(e["type"] == "command" for e in result["events"])


def test_missing_provider_is_a_failed_task_not_a_success(tmp_path):
    result = execute("run the application tests", state=make_state(tmp_path))
    assert result["status"] == "failed" and result["error"]["code"] == "TASK_REFUSED"


def test_provider_error_preserved(tmp_path):
    class Broken(Planner):
        def complete(self, *args, **kwargs):
            raise ProviderError("provider refused", status=401)

    result = execute("run the task", state=make_state(tmp_path, Broken()))
    assert result["status"] == "error" and result["error"]["code"] == "PROVIDER_ERROR"


def test_explicit_workspace_is_passed_to_the_shared_boundary(monkeypatch, tmp_path):
    from arcen.server import app

    seen = []
    fake = FakeTurnRegistry()

    def factory(config, *, workspace=None):
        seen.append(workspace)
        return fake

    monkeypatch.setattr(app, "create_turn_registry", factory)
    result = execute("run the task", state=make_state(tmp_path, Planner()), workspace=str(tmp_path))
    assert seen == [str(tmp_path)] and result["workspace_mode"] == "snapshot_requested"
    assert result["status"] == "ok" and fake.closed


def test_cli_json_and_no_tty(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path), "ARCEN_CONFIG_PATH": str(tmp_path / "config.yaml")}
    proc = subprocess.run(
        [sys.executable, "-m", "arcen.headless", "hello", "--json"],
        check=False,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["status"] == "ok"


def test_cli_run_error_exits_nonzero_and_keeps_stdout_json(tmp_path):
    # An impossible workspace fails without ever executing a host command.
    env = {**os.environ, "HOME": str(tmp_path), "ARCEN_CONFIG_PATH": str(tmp_path / "config.yaml")}
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "arcen.headless",
            "do work",
            "--json",
            "--workspace",
            str(tmp_path / "missing"),
        ],
        check=False,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=25,
    )
    result = json.loads(proc.stdout)
    assert proc.returncode != 0 and result["error"]["code"] == "SANDBOX_UNAVAILABLE"
    assert "Workspace snapshot rejected" in result["error"]["message"]


def test_harness_ref_is_explicitly_rejected(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "arcen.headless", "work", "--json", "--harness", "candidate"],
        check=False,
        env={**os.environ, "HOME": str(tmp_path)},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert proc.returncode != 0 and "no harness reference was applied" in proc.stderr


def test_real_docker_headless_workspace_when_enabled(tmp_path):
    if os.environ.get("ARCEN_TEST_DOCKER_ISOLATION") != "1":
        pytest.skip("requires ARCEN_TEST_DOCKER_ISOLATION=1 and a real Docker daemon/image")
    pytest.importorskip("docker")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "input.txt"
    source.write_text("host-original")

    class WorkspacePlanner(Planner):
        def complete(self, role, messages, **kwargs):
            if "Return ONLY the word" in messages[-1]["content"]:
                return super().complete(role, messages, **kwargs)
            return LLMResponse(
                text=json.dumps(
                    [
                        {
                            "title": "edit",
                            "tool": "bash",
                            "args": {
                                "cmd": "test -f input.txt && printf container-change > input.txt"
                            },
                        }
                    ]
                ),
                model="mock",
                tokens={"input": 1, "output": 1},
            )

    result = execute(
        "edit the file", state=make_state(tmp_path, WorkspacePlanner()), workspace=str(workspace)
    )
    if result["status"] != "ok":
        pytest.fail("Headless execution failed:\n" + json.dumps(result, indent=2), pytrace=False)
    assert source.read_text() == "host-original"
