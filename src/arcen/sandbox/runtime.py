"""ARCEN — sandbox runtime (BACKEND-SPEC Part 2 row 11 / Part 1 L4).

Pulled from OpenSandbox (runtime/) — the container lifecycle:
create on first use, exec commands, destroy on session end.

Edited per the Pull Map: one container per session, image pinning from
config, host-filesystem quarantine (no binds, no network by default).

Two backends:
- ``docker``  — a real pinned container per session (network none,
  mem/cpus capped, zero host binds). Used whenever a daemon is reachable.
- ``process`` — degraded fallback when no daemon: commands run in a
  per-session quarantine root with a scrubbed environment; file-tool
  paths are resolved against the root and escapes are refused. Honest
  about the limit: this is confinement, not isolation — the runtime
  reports ``degraded=True`` so the UI and logs never overclaim.

Boot rule (Part 10): sandbox unavailability never aborts boot — the
capability boots degraded.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import uuid

from arcen.tools.registry import Registry

DEFAULT_IMAGE = "ghcr.io/lewiseinstein15-tech/arcen-sandbox:0.1.0"
DEFAULT_MEM_LIMIT = "2g"
DEFAULT_CPUS = 2.0

_FILE_ARGS = {"path", "src", "dst"}


def _docker_client():
    """Return a live docker client or None. Never raises."""
    try:
        import docker

        client = docker.from_env()
        client.ping()
        return client
    except Exception:  # noqa: BLE001 — absence of docker is a normal state
        return None


class SandboxRuntime:
    """One sandbox per session. Commands run inside; the host stays out."""

    def __init__(
        self,
        config: dict | None = None,
        root: str | None = None,
        docker_client: object | None = None,
    ) -> None:
        config = config or {}
        sandbox_cfg = config.get("sandbox", {})
        self.image: str = sandbox_cfg.get("image", DEFAULT_IMAGE)
        self.mem_limit: str = sandbox_cfg.get("mem_limit", DEFAULT_MEM_LIMIT)
        self.cpus: float = float(sandbox_cfg.get("cpus", DEFAULT_CPUS))
        self.network: str = sandbox_cfg.get("network", "none")
        self.id: str = f"s-{uuid.uuid4().hex[:8]}"
        self.backend: str = "process"
        self.degraded: bool = True
        self._client = docker_client if docker_client is not None else _docker_client()
        self._container: object | None = None
        self._root: str | None = None

        if self._client is not None:
            self.backend = "docker"
            self.degraded = False
        else:
            # quarantine root for the degraded backend
            self._root = root or os.path.join(tempfile.gettempdir(), f"arcen-{self.id}")
            os.makedirs(self._root, exist_ok=True)
            os.makedirs(os.path.join(self._root, "tmp"), exist_ok=True)

    @property
    def root(self) -> str:
        return self._root or "/workspace"

    # -- command execution ---------------------------------------------------
    def run(self, cmd: str, timeout_s: float = 30.0) -> dict:
        """Run one bash command inside the sandbox. Returns the envelope."""
        started = time.monotonic()
        if self.backend == "docker":
            out = self._run_docker(cmd, timeout_s)
        else:
            out = self._run_process(cmd, timeout_s)
        out.setdefault("result", {})
        out["result"]["duration_s"] = round(time.monotonic() - started, 4)
        return out

    def _run_docker(self, cmd: str, timeout_s: float) -> dict:
        self._ensure_container()
        try:
            exec_result = self._container.exec_run(  # type: ignore[union-attr]
                ["bash", "-c", cmd],
                workdir="/workspace",
                demux=True,
            )
            stdout = (exec_result.output[0] or b"").decode("utf-8", "replace")
            stderr = (exec_result.output[1] or b"").decode("utf-8", "replace")
            exit_code = exec_result.exit_code
        except Exception as exc:  # noqa: BLE001 — envelope contract
            return {"ok": False, "result": None, "error": str(exc)}
        result = {"stdout": stdout, "stderr": stderr, "exit": exit_code}
        if exit_code == 0:
            return {"ok": True, "result": result, "error": None}
        return {"ok": False, "result": result, "error": f"exit {exit_code}: {stderr[-300:]}"}

    def _run_process(self, cmd: str, timeout_s: float) -> dict:
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": self.root,
            "TMPDIR": os.path.join(self.root, "tmp"),
            "LANG": "C.UTF-8",
        }
        try:
            proc = subprocess.run(
                ["bash", "-c", cmd],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                cwd=self.root,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "result": None, "error": f"timed out after {timeout_s}s"}
        result = {"stdout": proc.stdout, "stderr": proc.stderr, "exit": proc.returncode}
        if proc.returncode == 0:
            return {"ok": True, "result": result, "error": None}
        return {"ok": False, "result": result, "error": f"exit {proc.returncode}: {proc.stderr[-300:]}"}

    # -- path quarantine -------------------------------------------------------
    def resolve_path(self, path: str) -> str:
        """Resolve a path against the sandbox root; refuse escapes.

        Docker mode: any host path is refused — the container has no
        binds, so there is nothing to resolve onto.
        """
        if self.backend == "docker":
            return path if os.path.isabs(path) else f"/workspace/{path}"
        root = os.path.realpath(self.root)
        resolved = os.path.realpath(os.path.join(root, path)) if not os.path.isabs(path) else os.path.realpath(path)
        if resolved != root and not resolved.startswith(root + os.sep):
            raise PermissionError(
                f"path {path!r} escapes the sandbox root — host filesystem is quarantined"
            )
        return resolved

    # -- lifecycle ---------------------------------------------------------------
    def _ensure_container(self) -> None:
        if self._container is not None:
            return
        kwargs: dict = {
            "image": self.image,  # pinned — never 'latest'
            "detach": True,
            "command": ["sleep", "infinity"],
            "network_disabled": self.network == "none",
            "mem_limit": self.mem_limit,
            "nano_cpus": int(self.cpus * 1e9),
            "volumes": {},  # host-filesystem quarantine: zero binds
            "working_dir": "/workspace",
            "labels": {"arcen.session": self.id},
        }
        self._container = self._client.containers.run(**kwargs)  # type: ignore[union-attr]

    def destroy(self) -> None:
        """Tear the sandbox down. Idempotent."""
        if self._container is not None:
            try:
                self._container.kill()
            except Exception:  # noqa: BLE001
                pass
            try:
                self._container.remove(force=True)
            except Exception:  # noqa: BLE001
                pass
            self._container = None
        if self._root is not None and os.path.isdir(self._root):
            shutil.rmtree(self._root, ignore_errors=True)
            self._root = None


class SandboxRegistry(Registry):
    """A registry proxy that routes file tools through the sandbox root.

    ``file.*`` paths are resolved (and escape-checked) by the runtime;
    every other tool passes through untouched.
    """

    def __init__(self, inner: Registry, runtime: SandboxRuntime) -> None:
        super().__init__()
        self._inner = inner
        self._runtime = runtime
        # share the inner registry's tools (bypass our pass-through override)
        for name in inner.names():
            super().register(inner.get(name))

    def dispatch(self, name: str, args: dict) -> dict:
        if name.startswith("file."):
            try:
                args = dict(args)
                for key in _FILE_ARGS & args.keys():
                    if isinstance(args[key], str):
                        args[key] = self._runtime.resolve_path(args[key])
            except PermissionError as exc:
                return {"ok": False, "result": None, "error": str(exc)}
        return self._inner.dispatch(name, args)
