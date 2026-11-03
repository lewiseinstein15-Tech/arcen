"""Score original local tasks in the existing Docker-only turn boundary.

No candidate code is executed on the host. A scorer run is not an agent run.
"""

from __future__ import annotations

import base64
import shlex
import tempfile
from pathlib import Path

from arcen.sandbox.patch_validation import validate_patch
from arcen.sandbox.turn import DockerTurnRegistry
from bench.local_bank import load_tasks

# Runs inside the isolated disposable container, not on the host. A distinct
# exit code distinguishes a test failure from unknown runtime failures.
_PROGRAM = r"""import base64, subprocess, sys
patch = base64.b64decode(sys.argv[1], validate=True)
for args in (["git", "apply", "--check", "--", "-"], ["git", "apply", "--", "-"]):
    result = subprocess.run(args, input=patch, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode:
        sys.exit(20)
tests = subprocess.run([sys.executable, "-I", "-m", "unittest", "discover", "-s", ".", "-p", "test_solution.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
sys.exit(0 if tests.returncode == 0 else 10)
"""
MAX_LOCAL_PATCH = 32 * 1024  # shell argv transport cap, below the artifact cap


class LocalDockerScorer:
    def __init__(self, config, *, registry_factory=DockerTurnRegistry):
        self.config = config
        self.registry_factory = registry_factory
        self.last_error = None

    def score(self, task_id: str, patch: bytes) -> bool | None:
        self.last_error = None
        task = next((task for task in load_tasks() if task["id"] == task_id), None)
        if task is None:
            raise ValueError("unknown local task")
        if len(patch) > MAX_LOCAL_PATCH:
            raise ValueError("local benchmark patch exceeds transport limit")
        if validate_patch(patch) != ["solution.py"]:
            raise ValueError("local benchmark patches must change only solution.py")
        encoded = base64.b64encode(patch).decode("ascii")
        command = "python -I -c " + shlex.quote(_PROGRAM) + " " + shlex.quote(encoded)
        registry = None
        with tempfile.TemporaryDirectory(prefix="arcen-bench-") as temporary:
            workspace = Path(temporary)
            for name, content in task["files"].items():
                (workspace / name).write_text(content, encoding="utf-8")
            try:
                registry = self.registry_factory(self.config, workspace=str(workspace))
                envelope = registry.dispatch("bash", {"cmd": command, "timeout_s": 120.0})
                result = envelope.get("result") or {}
                code = result.get("exit")
                if type(code) is int and code == 0 and envelope.get("ok"):
                    return True
                if type(code) is int and code in (10, 20):
                    return False
                self.last_error = str(
                    envelope.get("error") or "scorer returned no recognized exit code"
                )
                return None
            finally:
                if registry is not None:
                    registry.close(strict=True)
