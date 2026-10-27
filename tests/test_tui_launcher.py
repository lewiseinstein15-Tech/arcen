"""Managed-server launcher — one-command TUI startup.

Unit tests cover the attach/spawn decision tree with injected seams; one
integration test really spawns uvicorn on an ephemeral port and tears it
down, proving `arcen-tui` works with no server pre-running.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("textual")

from arcen.tui import launcher
from arcen.tui.launcher import (
    ManagedServer,
    check_health,
    ensure_server,
    find_free_port,
    is_localhost,
)


class FakeManager:
    """Spawner seam recording lifecycle calls."""

    def __init__(self, port: int, log_path: Path) -> None:
        self.port = port
        self.log_path = log_path
        self.url = f"http://127.0.0.1:{port}"
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


# ------------------------------------------------------------------ helpers


def test_find_free_port_returns_bindable_port():
    port = find_free_port()
    assert isinstance(port, int) and 1024 <= port <= 65535
    # the returned port must actually be bindable right now
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", port))


def test_find_free_port_falls_back_when_preferred_taken():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.bind(("127.0.0.1", 0))
        occupied = holder.getsockname()[1]
        chosen = find_free_port(occupied)
        assert chosen != occupied


def test_is_localhost_classification():
    assert is_localhost("http://127.0.0.1:3002")
    assert is_localhost("http://localhost:3002")
    assert is_localhost("http://[::1]:3002")
    assert not is_localhost("http://10.0.0.5:3002")
    assert not is_localhost("https://arcen.example.com")


def test_check_health_never_raises_on_dead_port():
    dead_port = find_free_port()
    assert check_health(f"http://127.0.0.1:{dead_port}", timeout=0.5) is False


# ------------------------------------------------------------------ decision tree


def test_attach_when_server_already_healthy():
    url, manager = ensure_server(
        "http://127.0.0.1:3002",
        health=lambda u: True,  # something already answers
        spawner=lambda **kw: pytest.fail("must not spawn when healthy"),
    )
    assert url == "http://127.0.0.1:3002"
    assert manager is None  # never manage a server we did not start


def test_spawn_on_default_port_when_unhealthy():
    spawned: list[dict] = []

    def spawner(*, port: int, log_path: Path) -> FakeManager:
        spawned.append({"port": port, "log_path": log_path})
        return FakeManager(port, log_path)

    url, manager = ensure_server(
        "http://127.0.0.1:3002", health=lambda u: False, spawner=spawner,
        log_path=Path("/tmp/arcen-tui-test.log"),
    )
    assert manager is not None and isinstance(manager, FakeManager)
    assert url == manager.url
    assert spawned[0]["port"] > 0
    assert spawned[0]["log_path"] == Path("/tmp/arcen-tui-test.log")


def test_no_serve_refuses_instead_of_spawning():
    with pytest.raises(SystemExit, match="arcen serve"):
        ensure_server("http://127.0.0.1:3002", serve=False, health=lambda u: False)


def test_remote_unreachable_is_an_error_not_a_local_spawn():
    with pytest.raises(SystemExit, match="remote ARCEN server"):
        ensure_server("http://10.0.0.5:3002", health=lambda u: False)


def test_explicit_busy_port_moves_to_ephemeral():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.bind(("127.0.0.1", 0))
        busy = holder.getsockname()[1]  # held open for the whole test
        url, manager = ensure_server(
            f"http://127.0.0.1:{busy}",
            health=lambda u: False,
            spawner=FakeManager,
        )
        try:
            assert manager is not None
            assert manager.port != busy
            assert url == f"http://127.0.0.1:{manager.port}"
        finally:
            manager.stop()


# ------------------------------------------------------------------ real process


def test_managed_server_spawns_uvicorn_and_reaches_health(tmp_path):
    port = find_free_port()
    log_path = tmp_path / "tui-server.log"
    manager = ManagedServer(port=port, log_path=log_path)
    try:
        manager.start()
        assert manager._process is not None and manager._process.poll() is None
        manager.wait_ready(timeout=20)
        assert check_health(manager.url) is True
        # the child's output was redirected, never inherited by the TUI
        assert log_path.exists() and log_path.stat().st_size > 0
    finally:
        manager.stop()

    # process is gone and stop() is idempotent
    assert manager._process is None
    manager.stop()
    # the port is released after shutdown
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
                break
            except OSError:
                time.sleep(0.1)
    else:  # pragma: no cover — flaky-environment guard
        pytest.fail("managed server did not release its port")


def test_wait_ready_raises_when_child_dies_early(tmp_path):
    manager = ManagedServer(port=find_free_port(), log_path=tmp_path / "dead.log")

    # replace the uvicorn child with a process that exits immediately
    manager._log_file = (tmp_path / "dead.log").open("a")
    manager._process = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.exit(3)"],
        stdout=manager._log_file,
        stderr=subprocess.STDOUT,
    )
    try:
        with pytest.raises(RuntimeError, match="exited during startup"):
            manager.wait_ready(timeout=5)
    finally:
        manager.stop()


def test_default_log_path_lives_under_arcen_home():
    path = launcher.default_log_path()
    assert path.name == "tui-server.log"
    assert path.parent.name == ".arcen"
