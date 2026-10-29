"""Fail-closed Docker execution boundary for server turns.

Only ``bash`` is supported here. Other tools must be ported to the isolated
boundary explicitly; none can silently fall through to a host registry.
No process fallback, host mounts, host environment, or network is permitted.
"""

from __future__ import annotations

import logging
import math
import posixpath
import uuid
from typing import Any

from arcen.tools.bash import BashArgs

log = logging.getLogger(__name__)


class IsolationUnavailable(RuntimeError):
    """A turn cannot safely start its isolated executor."""


class DockerTurnRegistry:
    """Own one network-disabled, disposable container for a single turn."""

    supports_host_diff = False

    def __init__(
        self, config, *, docker_client: Any | None = None, workspace: str | None = None
    ) -> None:
        sandbox = config.sandbox
        if sandbox.backend == "process":
            raise IsolationUnavailable(
                "The process backend is not an isolation boundary; tool execution is disabled. "
                "Configure Docker and set sandbox.backend to auto or docker."
            )
        if sandbox.network != "none":
            raise IsolationUnavailable("Tool execution requires sandbox.network=none.")
        self._container = None
        snapshot = None
        if workspace is not None:
            from arcen.sandbox.workspace import WorkspaceError, snapshot_workspace

            try:
                snapshot = snapshot_workspace(workspace)
            except (WorkspaceError, OSError) as exc:
                raise IsolationUnavailable(f"Workspace snapshot rejected: {exc}") from exc
        try:
            if docker_client is None:
                import docker

                docker_client = docker.from_env()
            docker_client.ping()
            self._client = docker_client
            # Never pull automatically: an operator must supply the selected image.
            docker_client.images.get(sandbox.image)
            self._container = docker_client.containers.run(
                image=sandbox.image,
                entrypoint=["sleep"],
                command=["infinity"],
                detach=True,
                network_disabled=True,
                network_mode="none",
                volumes={},
                use_config_proxy=False,
                read_only=True,
                tmpfs={
                    "/workspace": "rw,nosuid,nodev,mode=1777,size=512m",
                    "/tmp": "rw,nosuid,nodev,mode=1777,size=128m",
                },
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                user="65534:65534",
                pids_limit=128,
                mem_limit=sandbox.mem_limit,
                nano_cpus=int(sandbox.cpus * 1e9),
                working_dir="/workspace",
                environment={
                    "HOME": "/tmp",
                    "LANG": "C.UTF-8",
                    "PATH": "/usr/local/bin:/usr/bin:/bin",
                },
                labels={"arcen.turn": uuid.uuid4().hex},
            )
            self._container.reload()
            attrs = self._container.attrs
            host, inner = attrs["HostConfig"], attrs["Config"]
            if (
                host.get("Privileged")
                or not host.get("ReadonlyRootfs")
                or host.get("NetworkMode") != "none"
                or host.get("Binds")
                or "ALL" not in (host.get("CapDrop") or [])
                or not any(
                    x.startswith("no-new-privileges") for x in (host.get("SecurityOpt") or [])
                )
                or inner.get("User") != "65534:65534"
                or any(m.get("Type") != "tmpfs" for m in attrs.get("Mounts", []))
            ):
                raise RuntimeError("Docker did not enforce the required container policy")
            if snapshot is not None and not self._container.put_archive("/workspace", snapshot):
                raise RuntimeError("Docker refused the workspace snapshot")
        except Exception as exc:
            if self._container is not None:
                self.close()
            raise IsolationUnavailable(
                "Docker isolation unavailable; tool execution is disabled. "
                "Ensure the Docker daemon is running and the configured sandbox image is installed."
            ) from exc

    def dispatch(self, name: str, args: dict) -> dict:
        if name != "bash":
            return {
                "ok": False,
                "result": None,
                "error": f"tool {name!r} is not yet available inside the isolated executor",
            }
        try:
            a = BashArgs.model_validate(args)
            if not math.isfinite(a.timeout_s):
                raise ValueError("timeout must be finite")
            cwd = a.cwd or "/workspace"
            if not cwd.startswith("/"):
                cwd = posixpath.join("/workspace", cwd)
            cwd = posixpath.normpath(cwd)
            if cwd != "/workspace" and not cwd.startswith("/workspace/"):
                raise ValueError("working directory must be inside /workspace")
            # GNU timeout is installed in the pinned image. The shell is an
            # argv element, not interpolated into a host-side command.
            command = ["timeout", "--kill-after=2s", f"{a.timeout_s:g}s", "bash", "-c", a.cmd]
            # Stream through a bounded host buffer: untrusted output must not
            # be allowed to exhaust the server's memory. When the limit is
            # exceeded, kill this disposable container rather than letting
            # a noisy process continue in the background.
            api = self._client.api
            created = api.exec_create(
                self._container.id,
                cmd=command,
                workdir=cwd,
                user="65534:65534",
                privileged=False,
                environment={
                    "HOME": "/tmp",
                    "LANG": "C.UTF-8",
                    "PATH": "/usr/local/bin:/usr/bin:/bin",
                },
            )
            exec_id = created["Id"]
            stream = api.exec_start(exec_id, stream=True, demux=True)
            stdout, stderr = bytearray(), bytearray()
            try:
                for out_chunk, err_chunk in stream:
                    if (
                        len(stdout) + len(stderr) + len(out_chunk or b"") + len(err_chunk or b"")
                        > 256 * 1024
                    ):
                        self._container.kill()
                        return {
                            "ok": False,
                            "result": None,
                            "error": "sandbox output exceeded 256 KiB; container stopped",
                        }
                    stdout.extend(out_chunk or b"")
                    stderr.extend(err_chunk or b"")
            finally:
                if hasattr(stream, "close"):
                    stream.close()
            exit_code = api.exec_inspect(exec_id)["ExitCode"]
            if exit_code is None:
                return {"ok": False, "result": None, "error": "sandbox command did not exit"}
            output = {
                "stdout": stdout.decode("utf-8", "replace"),
                "stderr": stderr.decode("utf-8", "replace"),
                "exit": exit_code,
            }
            return {
                "ok": exit_code == 0,
                "result": output,
                "error": None if exit_code == 0 else f"exit {exit_code}: {output['stderr'][-300:]}",
            }
        except Exception as exc:  # noqa: BLE001 — tool failures are values
            return {"ok": False, "result": None, "error": str(exc)}

    def close(self) -> None:
        """Remove the container; do not leave generated workloads behind."""
        container, self._container = self._container, None
        if container is None:
            return
        try:
            container.remove(force=True)
        except Exception:
            log.exception("Failed to remove isolated turn container")


def execution_status(config) -> dict:
    """Report the policy actually used by the server, not a hypothetical backend."""
    from arcen.sandbox.runtime import docker_status

    sandbox = config.sandbox
    status = docker_status(sandbox.image)
    if sandbox.backend == "process":
        reason = "process backend is not isolated; tool execution is disabled"
    elif sandbox.network != "none":
        reason = "tool execution requires sandbox.network=none"
    elif not status["docker_available"]:
        reason = "Docker SDK missing or daemon unreachable; tool execution is disabled"
    elif not status["image_present"]:
        reason = "sandbox image is not installed; tool execution is disabled"
    else:
        reason = "Docker and image present; isolation is checked when a turn starts"
        return {
            **status,
            "backend": sandbox.backend,
            "effective": "docker",
            "reason": reason,
            "degraded": False,
            "supported_tools": ["bash"],
        }
    return {
        **status,
        "backend": sandbox.backend,
        "effective": "unavailable",
        "reason": reason,
        "degraded": True,
        "supported_tools": ["bash"],
    }


def create_turn_registry(config, *, workspace: str | None = None) -> DockerTurnRegistry:
    return DockerTurnRegistry(config, workspace=workspace)
