"""Regression tests for the server's fail-closed isolation boundary.

Docker is mocked here; these are not evidence of real container isolation.
"""

from types import SimpleNamespace

import pytest

from arcen.config import ArcenConfig
from arcen.sandbox.turn import DockerTurnRegistry, IsolationUnavailable, execution_status


class Container:
    def __init__(self):
        self.calls = []
        self.removed = False
        self.killed = False
        self.id = "test-container"
        self.attrs = {
            "HostConfig": {
                "Privileged": False,
                "ReadonlyRootfs": True,
                "NetworkMode": "none",
                "Binds": [],
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
            },
            "Config": {"User": "65534:65534"},
            "Mounts": [],
        }

    def reload(self):
        pass

    def exec_run(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return SimpleNamespace(exit_code=0, output=(b"ok\n", b""))

    def kill(self):
        self.killed = True

    def remove(self, force=False):
        self.removed = force


class FakeDocker:
    def __init__(self):
        self.container = Container()
        self.images = SimpleNamespace(get=lambda image: object())
        self.containers = SimpleNamespace(run=self.run)
        self.run_args = None
        self.api = SimpleNamespace(
            exec_create=self.exec_create,
            exec_start=self.exec_start,
            exec_inspect=lambda eid: {"ExitCode": 0},
        )
        self.output = [(b"ok\n", b"")]

    def exec_create(self, container, cmd, **kwargs):
        self.container.calls.append((cmd, kwargs))
        return {"Id": "exec-id"}

    def exec_start(self, eid, stream, demux):
        return iter(self.output)

    def ping(self):
        return True

    def run(self, **kwargs):
        self.run_args = kwargs
        return self.container


def test_container_configuration_and_command_do_not_use_host():
    docker = FakeDocker()
    reg = DockerTurnRegistry(ArcenConfig(), docker_client=docker)
    spec = docker.run_args
    assert spec["network_disabled"] is True and spec["network_mode"] == "none"
    assert spec["volumes"] == {} and spec["read_only"] is True
    assert spec["use_config_proxy"] is False
    assert spec["cap_drop"] == ["ALL"] and spec["security_opt"] == ["no-new-privileges:true"]
    assert spec["user"] == "65534:65534" and spec["pids_limit"] == 128
    assert spec["tmpfs"]["/workspace"].startswith("rw,nosuid,nodev")
    assert set(spec["environment"]) == {"HOME", "LANG", "PATH"}
    payload = "echo ok; cat /home/host/secret"
    response = reg.dispatch("bash", {"cmd": payload})
    assert response["ok"] and response["result"]["stdout"] == "ok\n"
    cmd, kwargs = docker.container.calls[0]
    assert cmd[-2:] == ["-c", payload] and cmd[0] == "timeout"
    assert kwargs["workdir"] == "/workspace"
    assert kwargs["user"] == "65534:65534" and kwargs["privileged"] is False
    reg.close()
    assert docker.container.removed


@pytest.mark.parametrize("name", ["file.read", "file.write", "search.web", "code.eval", "unknown"])
def test_unported_tools_never_dispatch_to_the_host(name):
    docker = FakeDocker()
    reg = DockerTurnRegistry(ArcenConfig(), docker_client=docker)
    response = reg.dispatch(name, {"path": "/etc/passwd"})
    assert not response["ok"] and "not yet available" in response["error"]
    assert docker.container.calls == []


@pytest.mark.parametrize("cwd", ["/etc", "../../etc", "/workspace/../../etc"])
def test_bash_rejects_workdir_outside_workspace(cwd):
    docker = FakeDocker()
    reg = DockerTurnRegistry(ArcenConfig(), docker_client=docker)
    assert not reg.dispatch("bash", {"cmd": "true", "cwd": cwd})["ok"]
    assert not docker.container.calls


def test_unavailable_docker_and_explicit_process_fail_closed():
    broken = FakeDocker()
    broken.ping = lambda: (_ for _ in ()).throw(RuntimeError("daemon down"))
    with pytest.raises(IsolationUnavailable, match="disabled"):
        DockerTurnRegistry(ArcenConfig(), docker_client=broken)
    cfg = ArcenConfig()
    cfg.sandbox.backend = "process"
    with pytest.raises(IsolationUnavailable, match="not an isolation boundary"):
        DockerTurnRegistry(cfg, docker_client=FakeDocker())
    cfg.sandbox.backend = "auto"
    cfg.sandbox.network = "bridge"
    with pytest.raises(IsolationUnavailable, match="network=none"):
        DockerTurnRegistry(cfg, docker_client=FakeDocker())


def test_status_reports_unavailable_without_docker(monkeypatch):
    from arcen.sandbox import runtime

    monkeypatch.setattr(runtime, "_docker_client", lambda: None)
    status = execution_status(ArcenConfig())
    assert status["effective"] == "unavailable" and status["degraded"]
    assert "execution is disabled" in status["reason"]


def test_rejects_and_removes_container_if_daemon_does_not_enforce_policy():
    docker = FakeDocker()
    docker.container.attrs["HostConfig"]["NetworkMode"] = "bridge"
    with pytest.raises(IsolationUnavailable):
        DockerTurnRegistry(ArcenConfig(), docker_client=docker)
    assert docker.container.removed and not docker.container.calls


def test_excessive_output_stops_container():
    docker = FakeDocker()
    docker.output = [(b"x" * (256 * 1024 + 1), b"")]
    reg = DockerTurnRegistry(ArcenConfig(), docker_client=docker)
    result = reg.dispatch("bash", {"cmd": "yes"})
    assert not result["ok"] and "output exceeded" in result["error"]
    assert docker.container.killed


def test_server_forge_and_temper_use_only_the_turn_registry(monkeypatch, tmp_path):
    import json
    import threading

    from fake_turn_registry import FakeTurnRegistry

    import arcen.server.app as server
    from arcen.llm.client import LLMResponse

    class Planner:
        def is_available(self):
            return True

        def complete(self, role, messages, **kwargs):
            content = messages[-1]["content"]
            if "Return ONLY the word" in content:
                return LLMResponse(text="CODE", model="stub", tokens={"input": 1, "output": 1})
            return LLMResponse(
                text=json.dumps([{"title": "check", "tool": "bash", "args": {"cmd": "true"}}]),
                model="stub",
                tokens={"input": 1, "output": 1},
            )

    cfg = ArcenConfig()
    cfg.session.dir = str(tmp_path)
    state = server.ServerState(cfg)
    state.llm = Planner()
    # An accidental dispatch to the ordinary host registry fails the test.
    state.registry = SimpleNamespace(dispatch=lambda *a, **kw: pytest.fail("host dispatch"))
    fake = FakeTurnRegistry()
    monkeypatch.setattr(server, "create_turn_registry", lambda config: fake)
    state.run_flags["r"] = threading.Event()
    server.run_turn("run test", "session-test", "r", state)
    events = state.emitters["session-test"].replay(0)
    assert events[-1]["type"] == "run.done" and events[-1]["status"] == "ok"
    assert len(fake.calls) >= 2  # FORGE plus TEMPER rerun(s)
    assert all(name == "bash" for name, _ in fake.calls)
    assert fake.closed


def test_forge_does_not_read_host_files_for_isolated_registry(monkeypatch):
    from fake_turn_registry import FakeTurnRegistry

    from arcen.agents import forge

    monkeypatch.setattr(forge, "_read", lambda path: pytest.fail("host file read"))
    executor = forge.ForgeExecutor(FakeTurnRegistry())
    events = executor.execute_step({"id": 1, "tool": "file.write", "args": {"path": "/etc/passwd"}})
    assert not events[1].ok


def test_real_docker_isolation_when_explicitly_enabled(monkeypatch, tmp_path):
    """Opt-in live proof; skipped unless a trusted local Docker daemon is supplied."""
    import os
    import shlex
    import uuid

    if os.environ.get("ARCEN_TEST_DOCKER_ISOLATION") != "1":
        pytest.skip("requires ARCEN_TEST_DOCKER_ISOLATION=1 and a real Docker daemon/image")
    pytest.importorskip("docker")
    marker = "ARCEN_SECRET_" + uuid.uuid4().hex
    monkeypatch.setenv(marker, "secret-value")
    hostfile = tmp_path / ("host-" + uuid.uuid4().hex)
    hostfile.write_text("host-only")
    reg = DockerTurnRegistry(ArcenConfig())
    try:
        # An absolute host path and the server's secret environment must not
        # appear in the container. A container write cannot alter the host.
        path = shlex.quote(str(hostfile))
        check = reg.dispatch("bash", {"cmd": f'test ! -e {path} && test -z "${{{marker}:-}}"'})
        assert check["ok"], check
        write = reg.dispatch(
            "bash", {"cmd": f"mkdir -p $(dirname {path}); printf changed > {path}"}
        )
        assert write["ok"], write
        assert hostfile.read_text() == "host-only"
        network = reg.dispatch(
            "bash",
            {
                "cmd": "python -c 'import socket; socket.create_connection((\"1.1.1.1\",53),timeout=2)'",
                "timeout_s": 5,
            },
        )
        assert not network["ok"], network
    finally:
        reg.close()
