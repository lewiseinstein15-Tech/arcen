"""Managed local server lifecycle for one-command TUI launches.

The TUI is a client of ``arcen serve`` — but asking the user to open a
second terminal is poor UX. This module makes ``arcen-tui`` self-contained:

1. probe the configured URL; if a server already answers ``/api/health``
   the TUI attaches to it and does NOT manage its lifetime (we never kill
   a server someone else started);
2. otherwise spawn ``uvicorn arcen.server.app:app`` as a child process on
   127.0.0.1 (preferred port 3002, else a free ephemeral port), wait until
   it is healthy, run the TUI, and terminate the child on exit.

The child's output goes to ``~/.arcen/tui-server.log`` so it can never
corrupt the Textual screen. Health checks and process creation are
injectable so the whole decision tree is unit-testable without sockets.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from contextlib import AbstractContextManager
from pathlib import Path
from urllib.parse import urlparse

import httpx

from arcen.tui.client import DEFAULT_BASE_URL

PREFERRED_PORT = 3002
HOST = "127.0.0.1"
READY_TIMEOUT_S = 30.0
POLL_INTERVAL_S = 0.25
LOG_FILENAME = "tui-server.log"


def default_log_path() -> Path:
    """``~/.arcen/tui-server.log`` — next to config.yaml and the sessions."""
    return Path(os.path.expanduser("~/.arcen")) / LOG_FILENAME


def is_localhost(url: str) -> bool:
    """True for the hosts we are allowed to spawn a server on."""
    host = (urlparse(url).hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1", ""}


def find_free_port(preferred: int = PREFERRED_PORT) -> int:
    """Return ``preferred`` when bindable, otherwise an ephemeral free port.

    A non-ARCEN process may already hold 3002 — never crash on it, just
    move to another port.
    """
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((HOST, port))
            except OSError:
                continue
            return int(probe.getsockname()[1])
    raise RuntimeError("no free TCP port available")  # pragma: no cover


def check_health(url: str, *, timeout: float = 2.0) -> bool:
    """One liveness probe. Never raises — a dead server is just False."""
    try:
        response = httpx.get(f"{url.rstrip('/')}/api/health", timeout=timeout)
    except httpx.HTTPError:
        return False
    if response.status_code != 200:
        return False
    try:
        return bool(response.json().get("ok"))
    except (ValueError, httpx.DecodingError):
        return False


class ManagedServer(AbstractContextManager):
    """A uvicorn child process whose lifetime is bound to the TUI."""

    def __init__(self, port: int, log_path: Path) -> None:
        self.port = port
        self.log_path = log_path
        self.url = f"http://{HOST}:{port}"
        self._process: subprocess.Popen | None = None
        self._log_file = None

    def start(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_file = self.log_path.open("a", buffering=1)
        self._log_file.write(
            f"\n--- arcen-tui managed server starting {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n"
        )
        argv = [
            sys.executable, "-m", "uvicorn",
            "arcen.server.app:app",
            "--host", HOST,
            "--port", str(self.port),
        ]
        self._process = subprocess.Popen(
            argv,
            stdout=self._log_file,
            stderr=subprocess.STDOUT,
            cwd=str(Path.home()),
        )
        # belt-and-braces: if the TUI dies hard, don't orphan the server
        import atexit

        atexit.register(self.stop)

    def wait_ready(self, *, timeout: float = READY_TIMEOUT_S) -> None:
        """Poll /api/health until the child answers or the budget expires."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._process is not None and self._process.poll() is not None:
                raise RuntimeError(
                    f"the ARCEN server exited during startup (code "
                    f"{self._process.returncode}); see {self.log_path}"
                )
            if check_health(self.url, timeout=1.5):
                return
            time.sleep(POLL_INTERVAL_S)
        raise TimeoutError(
            f"the ARCEN server did not become ready within {timeout:.0f}s; "
            f"see {self.log_path}"
        )

    def stop(self) -> None:
        """Graceful terminate, then SIGKILL if the child ignores it."""
        process = self._process
        if process is None:
            return
        self._process = None  # make stop() idempotent
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None

    def __exit__(self, *exc: object) -> None:
        self.stop()


def ensure_server(
    url: str = DEFAULT_BASE_URL,
    *,
    serve: bool = True,
    log_path: Path | None = None,
    health=check_health,
    spawner=None,
) -> tuple[str, ManagedServer | None]:
    """Resolve a reachable server URL, spawning one when allowed/needed.

    Returns ``(effective_url, manager)`` — ``manager`` is None when we
    attached to an existing server (caller must not stop it) or when
    ``serve=False``. Raises :class:`SystemExit` with an actionable message
    when no server is reachable and spawning is impossible/disallowed.

    ``health`` and ``spawner`` are injection seams for headless tests.
    """
    if health(url):
        return url, None

    if not serve:
        raise SystemExit(
            f"Cannot reach the ARCEN server at {url}.\n"
            "Start one with `arcen serve`, or rerun without --no-serve to let "
            "the TUI manage a local server itself."
        )

    if not is_localhost(url):
        raise SystemExit(
            f"Cannot reach the remote ARCEN server at {url}, and the TUI can "
            "only manage a local server on 127.0.0.1.\n"
            "Start that server, or point --url at a local address."
        )

    requested_port = urlparse(url).port
    # explicit local port: keep it when free, else move aside; default: try 3002
    port = find_free_port(requested_port or PREFERRED_PORT)

    log_path = log_path or default_log_path()
    if spawner is None:
        manager = ManagedServer(port=port, log_path=log_path)
        print(f"ARCEN server not reachable at {url} — starting a local server "
              f"on {HOST}:{port} …", flush=True)
        manager.start()
        manager.wait_ready()
        print(f"Server ready — launching TUI (server log: {log_path})", flush=True)
    else:
        # test seam: the fake spawner owns construction and readiness
        manager = spawner(port=port, log_path=log_path)

    return manager.url, manager
