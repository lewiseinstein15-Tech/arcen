"""T-012 / Test-plan T-05 (isolation half) — sandbox runtime.

Proves: bash runs inside the sandbox; the host working tree is
untouched; path escapes are refused; one sandbox per session; the
docker lifecycle (create/exec/destroy, pinned image, no binds) is
exercised through a fake client so it is testable without a daemon.
"""

import os
import subprocess
from pathlib import Path

import pytest

from arcen.sandbox.runtime import SandboxRegistry, SandboxRuntime
from arcen.tools.registry import load_builtin


def _fake_docker_client():
    """A docker client stand-in recording lifecycle calls."""

    class FakeContainer:
        def __init__(self) -> None:
            self.killed = False
            self.removed = False

        def kill(self):
            self.killed = True

        def remove(self, force=True):
            self.removed = True

        def exec_run(self, cmd, workdir=None, demux=False):
            out = (b"hi\n", b"")
            return type("R", (), {"output": out, "exit_code": 0})()

    class FakeContainers:
        def __init__(self) -> None:
            self.container = None
            self.calls: list[dict] = []

        def run(self, **kwargs):
            self.calls.append(kwargs)
            self.container = FakeContainer()
            return self.container

    class FakeClient:
        def __init__(self) -> None:
            self.containers = FakeContainers()

        def ping(self):
            return True

    return FakeClient()


def test_process_backend_runs_and_is_cwd_confined() -> None:
    rt = SandboxRuntime()  # no docker in the CI path → process backend
    assert rt.backend == "process"
    assert rt.degraded is True
    out = rt.run("pwd")
    assert out["ok"] is True
    assert out["result"]["stdout"].strip() == rt.root  # command ran inside the root
    rt.destroy()


def test_host_working_tree_untouched(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)  # simulate the host project tree
    before = sorted(p.name for p in tmp_path.iterdir())
    rt = SandboxRuntime()
    rt.run("echo hello > inside.txt")          # writes INSIDE the sandbox root
    rt.run("ls -la / > host_root_listing.txt") # inside too
    after = sorted(p.name for p in tmp_path.iterdir())
    assert before == after, "the host tree changed — isolation broken"
    assert (Path(rt.root) / "inside.txt").exists()
    rt.destroy()


def test_path_quarantine_refuses_escapes() -> None:
    rt = SandboxRuntime()
    with pytest.raises(PermissionError):
        rt.resolve_path("/etc/passwd")
    with pytest.raises(PermissionError):
        rt.resolve_path("../../etc/passwd")
    resolved = rt.resolve_path("notes/x.txt")
    assert resolved.startswith(rt.root)
    rt.destroy()


def test_registry_routing_blocks_escape_via_file_tools() -> None:
    inner = load_builtin()
    rt = SandboxRuntime()
    sandboxed = SandboxRegistry(inner, rt)
    out = sandboxed.dispatch("file.read", {"path": "/etc/hostname"})
    assert out["ok"] is False
    assert "quarantined" in out["error"]
    # relative writes land inside the root
    out = sandboxed.dispatch("file.write", {"path": "ok.txt", "content": "fine"})
    assert out["ok"] is True
    assert (Path(rt.root) / "ok.txt").read_text() == "fine"
    rt.destroy()


def test_one_sandbox_per_session() -> None:
    a, b = SandboxRuntime(), SandboxRuntime()
    assert a.id != b.id
    assert a.root != b.root
    a.destroy()
    b.destroy()


def test_docker_lifecycle_via_fake_client() -> None:
    client = _fake_docker_client()
    rt = SandboxRuntime(docker_client=client)
    assert rt.backend == "docker"
    assert rt.degraded is False
    out = rt.run("echo hi")
    assert out["ok"] is True  # fake exec output defaults
    call = client.containers.calls[0]
    # image pinned, no host binds, network off, resources capped
    assert call["image"] == rt.image and ":0.1.0" in call["image"]
    assert call["volumes"] == {}
    assert call["network_disabled"] is True
    assert call["mem_limit"] == "2g"
    assert call["nano_cpus"] == int(2.0 * 1e9)
    assert call["labels"]["arcen.session"] == rt.id
    rt.destroy()
    assert client.containers.container.killed and client.containers.container.removed


def test_destroy_is_idempotent() -> None:
    rt = SandboxRuntime()
    rt.destroy()
    rt.destroy()  # second call is a no-op, not a crash


def test_sandbox_registry_passthrough_for_non_file_tools() -> None:
    inner = load_builtin()
    rt = SandboxRuntime()
    sandboxed = SandboxRegistry(inner, rt)
    out = sandboxed.dispatch("math.eval", {"expr": "6 * 7"})
    assert out["ok"] is True and out["result"]["value"] == 42
    rt.destroy()
