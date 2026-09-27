"""ARCEN — bash tool (BACKEND-SPEC Part 2, row 6 — OpenHands tools/ pattern).

One tool: run a shell command, capture stdout/stderr/exit. Wrapped in the
frozen Tool schema (Part 3). Sandbox routing (one Docker container per
session) happens in ``arcen.sandbox.runtime``; this module executes with
subprocess and a hard timeout. Nonzero exit is a failure carried as a
value — ``execute`` never raises.
"""

from __future__ import annotations

import subprocess

from pydantic import BaseModel, Field

from .registry import BaseTool, _err, _ok


class BashArgs(BaseModel):
    cmd: str = Field(description="the shell command to run")
    timeout_s: float = Field(default=30.0, ge=0.1, le=600.0, description="hard timeout")
    cwd: str | None = Field(default=None, description="working directory (default: session cwd)")


class BashTool(BaseTool):
    name = "bash"
    description = (
        "Run one shell command and capture stdout, stderr, and the exit code. "
        "Use for builds, test runs, git, and any CLI work. One command per call; "
        "the command has a hard timeout."
    )
    version = "1.0.0"
    danger = "sandboxed"

    class Args(BashArgs):
        pass

    def execute(self, args: dict) -> dict:
        try:
            a = self.Args.model_validate(args)
        except Exception as exc:  # noqa: BLE001 — envelope contract
            return _err(f"invalid args: {exc}")
        try:
            proc = subprocess.run(
                ["bash", "-c", a.cmd],
                capture_output=True,
                text=True,
                timeout=a.timeout_s,
                cwd=a.cwd,
            )
        except subprocess.TimeoutExpired:
            return _err(f"command timed out after {a.timeout_s}s")
        except Exception as exc:  # noqa: BLE001 — envelope contract
            return _err(str(exc))
        result = {"stdout": proc.stdout, "stderr": proc.stderr, "exit": proc.returncode}
        if proc.returncode == 0:
            return _ok(result)
        tail = (proc.stderr or proc.stdout)[-500:].strip()
        return {"ok": False, "result": result, "error": f"exit {proc.returncode}: {tail}"}
