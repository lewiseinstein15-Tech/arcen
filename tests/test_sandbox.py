"""T-012 / Test-plan T-05 (isolation half) — sandbox runtime.

Proves: bash runs inside the sandbox; the host working tree is
untouched; path escapes are refused; one sandbox per session; the
docker lifecycle (create/exec/destroy, pinned image, no binds) is
exercised through a fake client so it is testable without a daemon.

Environment-mismatch fix (the "9 failing tests" round): backend
selection now requires the pinned image to be PRESENT — a daemon
alone is not enough. Every process-backend test forces the backend
via ``docker_client=False`` so the suite is deterministic on hosts
with docker, without docker, or with the image pulled.
"""

import os
import subprocess
from pathlib import Path

import pytest

from arcen.sandbox import runtime as runtime_mod
from arcen.sandbox.runtime import SandboxRegistry, SandboxRuntime
from arcen.tools.registry import load_builtin


@pytest.fixture(autouse=True)
def _fresh_pull_cache(monkeypatch):
    """Isolate the once-per-process auto-pull cache between tests."""
    monkeypatch.setattr(runtime_mod, "_PULL_TRIED", set())


def _fake_docker_client(image_present: bool = True, pullable: bool | None = None):
    """A docker client stand-in recording lifecycle calls.

    ``image_present=False`` simulates the "daemon up, image missing"
    laptop state that used to crash the docker path with a 500.
    ``pullable=True`` lets the trusted auto-pull succeed (get raises,
    pull returns) — the "image lives on ghcr" state.
    """
    if pullable is None:
        pullable = image_present

    class FakeImageRef:
        pass

    class FakeImages:
        def __init__(self) -> None:
            self.pull_calls: list[str] = []

        def get(self, ref):
            if image_present:
                return FakeImageRef()
            raise RuntimeError(f"404 Client Error: ImageNotFound for {ref}")

        def pull(self, ref, **_):
            self.pull_calls.append(ref)
            if pullable:
                return FakeImageRef()
            raise RuntimeError(f"pull denied — {ref} was never pushed")

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
            if not image_present:
                raise RuntimeError("500 Server Error: denied — image absent")
            self.container = FakeContainer()
            return self.container

    class FakeClient:
        def __init__(self) -> None:
            self.containers = FakeContainers()
            self.images = FakeImages()

        def ping(self):
            return True

    return FakeClient()


def test_process_backend_runs_and_is_cwd_confined() -> None:
    rt = SandboxRuntime(docker_client=False)  # forced: deterministic everywhere
    assert rt.backend == "process"
    assert rt.degraded is True
    out = rt.run("pwd")
    assert out["ok"] is True
    assert out["result"]["stdout"].strip() == rt.root  # command ran inside the root
    rt.destroy()


def test_host_working_tree_untouched(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)  # simulate the host project tree
    before = sorted(p.name for p in tmp_path.iterdir())
    rt = SandboxRuntime(docker_client=False)
    rt.run("echo hello > inside.txt")          # writes INSIDE the sandbox root
    rt.run("ls -la / > host_root_listing.txt") # inside too
    after = sorted(p.name for p in tmp_path.iterdir())
    assert before == after, "the host tree changed — isolation broken"
    assert (Path(rt.root) / "inside.txt").exists()
    rt.destroy()


def test_path_quarantine_refuses_escapes() -> None:
    rt = SandboxRuntime(docker_client=False)
    with pytest.raises(PermissionError):
        rt.resolve_path("/etc/passwd")
    with pytest.raises(PermissionError):
        rt.resolve_path("../../etc/passwd")
    resolved = rt.resolve_path("notes/x.txt")
    assert resolved.startswith(rt.root)
    rt.destroy()


def test_registry_routing_blocks_escape_via_file_tools() -> None:
    inner = load_builtin()
    rt = SandboxRuntime(docker_client=False)
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
    a, b = SandboxRuntime(docker_client=False), SandboxRuntime(docker_client=False)
    assert a.id != b.id
    assert a.root != b.root
    assert a.root.startswith("/tmp") and b.root.startswith("/tmp")
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
    rt = SandboxRuntime(docker_client=False)
    rt.destroy()
    rt.destroy()  # second call is a no-op, not a crash


def test_sandbox_registry_passthrough_for_non_file_tools() -> None:
    inner = load_builtin()
    rt = SandboxRuntime(docker_client=False)
    sandboxed = SandboxRegistry(inner, rt)
    out = sandboxed.dispatch("math.eval", {"expr": "6 * 7"})
    assert out["ok"] is True and out["result"]["value"] == 42
    rt.destroy()


# -- the environment-mismatch contract (daemon up, image absent) ----------------

def test_docker_backend_requires_image_present() -> None:
    """Daemon alive + image absent → process fallback, never a 500 crash.

    This is the user's-laptop scenario, simulated hermetically through
    the fake client: the old runtime selected docker on daemon presence
    alone and then died pulling an image that was never pushed.
    """
    client = _fake_docker_client(image_present=False)
    rt = SandboxRuntime(docker_client=client)
    assert rt.backend == "process"
    assert rt.degraded is True
    assert rt.root != "/workspace"  # a real unique quarantine root
    out = rt.run("pwd")
    assert out["ok"] is True
    assert out["result"]["stdout"].strip() == rt.root
    with pytest.raises(PermissionError):
        rt.resolve_path("/etc/passwd")
    assert client.images.pull_calls  # the whitelisted default got ONE pull try
    rt.destroy()


def test_trusted_env_override_pulls_image(monkeypatch) -> None:
    """ARCEN_SANDBOX_IMAGE marks a ref trusted: pull attempted, docker wins."""
    monkeypatch.setenv("ARCEN_SANDBOX_IMAGE", "ghcr.io/lewiseinstein15-tech/arcen-sandbox:0.2.0")
    client = _fake_docker_client(image_present=False, pullable=True)  # absent locally, live on ghcr
    rt = SandboxRuntime(docker_client=client)
    assert rt.backend == "docker"  # ...but the trusted pull succeeded
    assert rt.degraded is False
    assert client.images.pull_calls == ["ghcr.io/lewiseinstein15-tech/arcen-sandbox:0.2.0"]
    rt.destroy()


def test_untrusted_image_is_never_pulled() -> None:
    """A ref outside the whitelist/override falls back with ZERO pull attempts."""
    client = _fake_docker_client(image_present=False)
    rt = SandboxRuntime(config={"sandbox": {"image": "random/untrusted:latest"}}, docker_client=client)
    assert rt.backend == "process"
    assert client.images.pull_calls == []  # no network gamble on unknown refs
    rt.destroy()


def test_runtime_container_failure_degrades_to_process() -> None:
    """Image present at init, container create failing mid-session → soft
    degrade on the first run, envelope returned, never a raised 500."""
    client = _fake_docker_client(image_present=True)
    rt = SandboxRuntime(docker_client=client)
    assert rt.backend == "docker"
    client.containers.run = lambda **kw: (_ for _ in ()).throw(RuntimeError("500 Server Error: denied"))
    out = rt.run("pwd")
    assert out["ok"] is True
    assert rt.backend == "process" and rt.degraded is True
    rt.destroy()


# -- T-038: configurable sandbox backend (auto / docker / process) -----------

def test_backend_process_forces_process_even_with_a_daemon() -> None:
    """backend='process' is deterministic — docker present changes nothing."""
    client = _fake_docker_client(image_present=True)
    rt = SandboxRuntime(docker_client=client, backend="process")
    assert rt.backend == "process"
    assert rt.degraded is True


def test_backend_docker_without_daemon_raises_no_silent_fallback() -> None:
    """backend='docker' + no daemon → a clear error, never a process degrade."""
    from arcen.sandbox.runtime import SandboxBackendError

    with pytest.raises(SandboxBackendError, match="no docker daemon"):
        SandboxRuntime(docker_client=False, backend="docker")


def test_backend_docker_with_image_runs_docker() -> None:
    client = _fake_docker_client(image_present=True)
    rt = SandboxRuntime(docker_client=client, backend="docker")
    assert rt.backend == "docker"
    assert rt.degraded is False
    out = rt.run("echo forced-docker")
    assert out["ok"] is True


def test_backend_docker_missing_image_warns_and_keeps_docker() -> None:
    """Image absent + forced docker → boot warning, docker kept — the
    runtime NEVER silently falls back to process on a pinned backend."""
    client = _fake_docker_client(image_present=False, pullable=False)
    rt = SandboxRuntime(docker_client=client, backend="docker")
    assert rt.backend == "docker"
    assert rt.degraded is False


def test_backend_invalid_value_rejected() -> None:
    with pytest.raises(ValueError, match="unknown sandbox backend"):
        SandboxRuntime(docker_client=False, backend="swarm")


def test_backend_from_config_dict() -> None:
    rt = SandboxRuntime(config={"sandbox": {"backend": "process"}}, docker_client=False)
    assert rt.backend == "process"


def test_backend_parameter_wins_over_config() -> None:
    rt = SandboxRuntime(
        config={"sandbox": {"backend": "docker"}}, docker_client=False, backend="process"
    )
    assert rt.backend == "process"


def test_backend_auto_unchanged_with_no_daemon() -> None:
    rt = SandboxRuntime(docker_client=False, backend="auto")
    assert rt.backend == "process" and rt.degraded is True


def test_docker_status_probe(monkeypatch) -> None:
    """docker_status never raises and reports the three Settings fields."""
    monkeypatch.setattr(runtime_mod, "_docker_client", lambda: None)
    status = runtime_mod.docker_status("some/image:1.0")
    assert status == {
        "docker_available": False,
        "image_present": False,
        "image": "some/image:1.0",
    }
