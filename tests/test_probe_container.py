"""Probe gateway lifecycle, redaction, and opt-in real-Docker smoke test."""

from __future__ import annotations

import os
import uuid
from typing import ClassVar

import pytest
from test_probe_workspace import repository

from arcen.config import ArcenConfig
from arcen.harness import probe_container
from arcen.harness.probe_container import open_probe_container
from arcen.harness.probe_workspace import snapshot_git_commit
from arcen.sandbox.turn import IsolationUnavailable


class FakeBoundary:
    created: ClassVar[list] = []

    def __init__(self, config, *, workspace):
        from pathlib import Path

        self.workspace = Path(workspace)
        assert (self.workspace / "src/main.py").read_text() == "print('committed')\n"
        self.closed = False
        self.calls = []
        self.__class__.created.append(self)

    def dispatch(self, name, args):
        self.calls.append((name, args))
        return {
            "ok": False,
            "result": {
                "stdout": "nested sk-abcdefghijklmnop test-token-123",
                "nested": [{"api-test-token-123": "test-token-123"}],
            },
            "error": "test-token-123",
        }

    def close(self):
        self.closed = True


def test_gateway_disposable_workspace_and_mandatory_redaction(tmp_path, monkeypatch):
    repo, commit = repository(tmp_path)
    snapshot = snapshot_git_commit(repo, commit)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", FakeBoundary)
    cfg = ArcenConfig(provider={"api_key": "test-token-123"})
    with open_probe_container(snapshot, cfg) as gateway:
        boundary = FakeBoundary.created[-1]
        result = gateway.dispatch("bash", {"cmd": "true"})
        assert "sk-abcdefghijklmnop" not in repr(result)
        assert "test-token-123" not in repr(result)
        assert "[REDACTED]" in repr(result)
        assert not gateway.supports_host_diff and not boundary.closed
        assert boundary.workspace.exists()
    assert boundary.closed and not boundary.workspace.exists()
    assert (repo / "src/main.py").read_text() == "print('committed')\n"


def test_env_secret_redacted_and_cleanup_on_user_error(tmp_path, monkeypatch):
    repo, commit = repository(tmp_path)
    snapshot = snapshot_git_commit(repo, commit)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", FakeBoundary)
    monkeypatch.setenv("PROBE_API_KEY", "test-token-123")
    cfg = ArcenConfig(provider={"api_key": "$PROBE_API_KEY"})
    with (
        pytest.raises(RuntimeError, match="test exception"),
        open_probe_container(snapshot, cfg) as gateway,
    ):
        boundary = FakeBoundary.created[-1]
        assert "test-token-123" not in repr(gateway.dispatch("bash", {"cmd": "true"}))
        raise RuntimeError("test exception")
    assert boundary.closed and not boundary.workspace.exists()


def test_constructor_failure_never_falls_back_and_cleans_workspace(tmp_path, monkeypatch):
    from pathlib import Path

    repo, commit = repository(tmp_path)
    snapshot = snapshot_git_commit(repo, commit)
    seen = []

    def refuse(config, *, workspace):
        seen.append(Path(workspace))
        raise IsolationUnavailable("no Docker")

    monkeypatch.setattr(probe_container, "DockerTurnRegistry", refuse)
    with (
        pytest.raises(IsolationUnavailable, match="no Docker"),
        open_probe_container(snapshot, ArcenConfig()),
    ):
        pytest.fail("must not run")
    assert len(seen) == 1 and not seen[0].exists()


def test_real_docker_probe_container_when_explicitly_enabled(tmp_path, monkeypatch):
    if os.environ.get("ARCEN_TEST_DOCKER_ISOLATION") != "1":
        pytest.skip("requires ARCEN_TEST_DOCKER_ISOLATION=1 and a real Docker daemon/image")
    pytest.importorskip("docker")
    repo, commit = repository(tmp_path)
    snapshot = snapshot_git_commit(repo, commit)
    marker = "ARCEN_HOST_SECRET_" + uuid.uuid4().hex
    monkeypatch.setenv(marker, "host-only-value")
    with open_probe_container(snapshot, ArcenConfig()) as gateway:
        result = gateway.dispatch(
            "bash",
            {
                "cmd": f'test -f src/main.py && test -z "${{{marker}:-}}" && printf changed > src/main.py'
            },
        )
        assert result["ok"] and result["result"]["exit_code"] == 0, result
    assert (repo / "src/main.py").read_text() == "print('committed')\n"
