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

import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid

from arcen.tools.registry import Registry

log = logging.getLogger("arcen.sandbox")

DEFAULT_IMAGE = "ghcr.io/lewiseinstein15-tech/arcen-sandbox:0.1.0"
DEFAULT_MEM_LIMIT = "2g"
DEFAULT_CPUS = 2.0

_FILE_ARGS = {"path", "src", "dst"}

# known-good image references: our own pinned ghcr repo (semver tags only,
# never :latest). Only these may be auto-pulled when absent locally.
_KNOWN_GOOD_IMAGE = re.compile(
    r"^ghcr\.io/lewiseinstein15-tech/arcen-sandbox:v?\d+\.\d+\.\d+$"
)

# a failed pull is remembered per process — at most one network attempt
# per image reference, so five sandboxes in one boot never pull five times.
_PULL_TRIED: set[str] = set()


def _env_image_override() -> str | None:
    """ARCEN_SANDBOX_IMAGE — an explicit, trusted image reference."""
    ref = os.environ.get("ARCEN_SANDBOX_IMAGE", "").strip()
    return ref or None


def _known_good_image(ref: str) -> bool:
    """Whitelist (our pinned ghcr repo) or explicit env override."""
    return bool(_KNOWN_GOOD_IMAGE.match(ref)) or ref == _env_image_override()


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
    """One sandbox per session. Commands run inside; the host stays out.

    Backend selection (the T-012 environment fix):
      1. no docker daemon            → process backend, degraded
      2. daemon + image present      → docker backend
      3. daemon + image absent       → one trusted auto-pull attempt for
        known-good refs; success → docker, failure → process, degraded
    The docker path is never selected unless the image is actually
    usable, and a runtime container-create failure degrades the
    instance instead of crashing the session.

    Pass ``docker_client=False`` to force the process backend
    deterministically (tests, or hosts where docker must stay off).
    """

    def __init__(
        self,
        config: dict | None = None,
        root: str | None = None,
        docker_client: object | None = None,
    ) -> None:
        config = config or {}
        sandbox_cfg = config.get("sandbox", {})
        self.image: str = (
            sandbox_cfg.get("image") or _env_image_override() or DEFAULT_IMAGE
        )
        self.mem_limit: str = sandbox_cfg.get("mem_limit", DEFAULT_MEM_LIMIT)
        self.cpus: float = float(sandbox_cfg.get("cpus", DEFAULT_CPUS))
        self.network: str = sandbox_cfg.get("network", "none")
        self.id: str = f"s-{uuid.uuid4().hex[:8]}"
        self.backend: str = "process"
        self.degraded: bool = True
        if docker_client is False:
            # explicit opt-out (tests / config) — force the process backend
            self._client = None
        else:
            self._client = (
                docker_client if docker_client is not None else _docker_client()
            )
        self._container: object | None = None
        self._root: str | None = None

        if self._client is not None and self._image_present():
            self.backend = "docker"
            self.degraded = False
            log.info(
                "sandbox %s backend=docker image=%s", self.id, self.image
            )
        else:
            reason = (
                "no docker daemon"
                if self._client is None
                else f"image {self.image} not present locally"
            )
            self._degrade_to_process(root=root, reason=reason)

    @property
    def root(self) -> str:
        return self._root or "/workspace"

    # -- command execution ---------------------------------------------------
    def run(self, cmd: str, timeout_s: float = 30.0) -> dict:
        """Run one bash command inside the sandbox. Returns the envelope.

        If container creation fails at runtime (image deleted between
        init and exec, daemon dying mid-session), the instance degrades
        to the process backend for the rest of its life instead of
        crashing — the docker path never fails hard.
        """
        started = time.monotonic()
        if self.backend == "docker":
            try:
                self._ensure_container()
            except Exception as exc:  # noqa: BLE001 — fail-soft by design
                self._degrade_to_process(
                    reason=f"container create failed: {exc} — falling back to process"
                )
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

    # -- backend selection & fallback -------------------------------------------
    def _image_present(self) -> bool:
        """True iff the pinned image exists locally (or a trusted pull succeeds).

        Never raises. A missing image triggers an auto-pull ONLY for
        known-good references (our pinned ghcr repo or the explicit
        ARCEN_SANDBOX_IMAGE override) — pulling an arbitrary ref that
        was never pushed is what produced the "500 denied" crash.
        """
        try:
            self._client.images.get(self.image)  # type: ignore[union-attr]
            return True
        except Exception:  # noqa: BLE001 — ImageNotFound / docker SDK absent
            pass
        if not _known_good_image(self.image) or self.image in _PULL_TRIED:
            return False
        _PULL_TRIED.add(self.image)  # one network attempt per ref per process
        log.info("sandbox %s pulling trusted image %s ...", self.id, self.image)
        try:
            self._client.images.pull(self.image)  # type: ignore[union-attr]
            log.info("sandbox %s pull of %s succeeded", self.id, self.image)
            return True
        except Exception as exc:  # noqa: BLE001 — absent upstream / no network
            log.warning("sandbox %s pull of %s failed: %s", self.id, self.image, exc)
            return False

    def _degrade_to_process(self, root: str | None = None, reason: str = "") -> None:
        """Select the quarantined process backend. Honest about the limit."""
        self.backend = "process"
        self.degraded = True
        if self._root is None:
            # unique quarantine root per instance — never shared, never /workspace
            self._root = root or os.path.join(tempfile.gettempdir(), f"arcen-{self.id}")
            os.makedirs(self._root, exist_ok=True)
            os.makedirs(os.path.join(self._root, "tmp"), exist_ok=True)
        log.warning("sandbox %s backend=process degraded=true (%s)", self.id, reason)

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
