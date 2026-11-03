"""ARCEN — TEMPER, the verifier (BACKEND-SPEC Part 1 / Part 2 row 3).

Pulled from SWE-agent (reviewer.py) — the adversarial review pass over
produced work.

Edited per the Pull Map:
- output reduced to a binary verdict: pass/fail plus reasons;
- emits ``verify.start`` / ``step.pass`` / ``step.fail`` on the frozen
  event schema;
- failed checks are re-run ``reruns`` times (default 1) to separate
  flaky checks from real failures — a check must fail every time.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable

from arcen.stream.events import Event, StepFail, StepPass, VerifyStart, to_line
from arcen.tools.registry import Registry, load_builtin


class TemperVerifier:
    """Tests adversarially. Reports pass/fail. Never fixes."""

    def __init__(
        self,
        registry: Registry,
        emit: Callable[[Event], None] | None = None,
        adversarial: bool = True,
        reruns: int = 1,
    ) -> None:
        self.registry = registry
        self.emit = emit
        self.adversarial = adversarial
        self.reruns = max(0, reruns)

    def verify(self, step: int, target: str, checks: list[str]) -> list[Event]:
        """Run every check command against the target.

        All green → ``step.pass``. Any check that fails on every allowed
        retry → ``step.fail`` with the failing reason.
        """
        verify_start = VerifyStart(seq=0, agent="TEMPER", target=target, ts=0.0)
        self._emit(verify_start)

        results: list[dict] = []
        failed: dict | None = None
        for check in checks:
            outcome = self._run_check(check)
            attempts = 1
            while not outcome["ok"] and attempts <= self.reruns:
                outcome = self._run_check(check)
                attempts += 1
            results.append({"check": check, "ok": outcome["ok"], "attempts": attempts})
            if not outcome["ok"] and failed is None:
                failed = {**outcome, "attempts": attempts}

        if failed is None:
            verdict = StepPass(
                seq=0,
                step=step,
                checks=[r["check"] for r in results],
                ts=0.0,
            )
        else:
            verdict = StepFail(
                seq=0,
                step=step,
                reason=failed["reason"],
                retry=max(0, failed["attempts"] - 1),
                ts=0.0,
            )
        self._emit(verdict)
        return [verify_start, verdict]

    def _run_check(self, check: str) -> dict:
        """One check = one bash dispatch through the registry."""
        started = time.monotonic()
        envelope = self.registry.dispatch("bash", {"cmd": check, "timeout_s": 120.0})
        duration = round(time.monotonic() - started, 4)
        if envelope["ok"]:
            return {"ok": True, "check": check, "reason": "", "duration_s": duration}
        result = envelope.get("result") or {}
        tail = (
            result.get("stderr") or result.get("stdout") or envelope.get("error") or ""
        ).strip()[-300:]
        return {"ok": False, "check": check, "reason": tail, "duration_s": duration}

    def _emit(self, event: Event) -> None:
        if self.emit is not None:
            self.emit(event)


# Fixed code executed only inside the same isolated registry as the work.  It
# inspects filenames/manifests without importing workspace code.
_DISCOVER_TESTS = r"""import json, os, re
npm = False
try:
    if not os.path.islink("package.json"):
        with open("package.json", "rb") as f:
            data = f.read(1048577)
        if len(data) <= 1048576:
            script = json.loads(data).get("scripts", {}).get("test")
            npm = isinstance(script, str) and bool(script.strip())
except (OSError, ValueError, AttributeError, TypeError):
    pass
cargo = os.path.isfile("Cargo.toml") and not os.path.islink("Cargo.toml")
go = os.path.isfile("go.mod") and not os.path.islink("go.mod")
py_tests = js_tests = go_tests = rust_tests = False
count = 0
for root, dirs, files in os.walk(".", followlinks=False):
    dirs[:] = [d for d in dirs if d not in {".git", ".venv", "venv", "node_modules", "target", "__pycache__"} and not os.path.islink(os.path.join(root, d))]
    count += len(dirs) + len(files)
    if count > 10000:
        raise RuntimeError("test discovery exceeded entry limit")
    for name in files:
        path = os.path.join(root, name)
        if os.path.islink(path):
            continue
        if name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py")):
            py_tests = True
        if re.search(r"(?:[._-](?:test|spec))\.(?:[cm]?[jt]sx?)$", name):
            js_tests = True
        if name.endswith("_test.go"):
            go_tests = True
        if cargo and name.endswith(".rs"):
            try:
                with open(path, "rb") as f:
                    content = f.read(1048577)
                if len(content) <= 1048576 and (re.search(rb"#\s*\[\s*(?:[a-zA-Z0-9_]+::)*test(?:\s*\(|\s*\])", content) or root.startswith("./tests")):
                    rust_tests = True
            except OSError:
                pass
commands = []
if py_tests: commands.append("python -m pytest -q")
if npm and js_tests: commands.append("npm test")
if cargo and rust_tests: commands.append("cargo test")
if go and go_tests: commands.append("go test ./...")
print(json.dumps({"command": commands[0] if commands else None}))"""


def verify_sandbox_tests(registry, *, step: int, target: str, emit) -> str:
    """Discover and run one bounded test suite, or report unverified."""
    import json
    import shlex

    discovery = registry.dispatch(
        "bash", {"cmd": "python -I -c " + shlex.quote(_DISCOVER_TESTS), "timeout_s": 30.0}
    )
    result = discovery.get("result") or {}
    try:
        if not discovery.get("ok") or result.get("exit") != 0:
            raise ValueError("test discovery failed")
        command = json.loads(result.get("stdout", ""))["command"]
        if command not in {None, "python -m pytest -q", "npm test", "cargo test", "go test ./..."}:
            raise ValueError("unexpected test discovery result")
    except (ValueError, TypeError, KeyError):
        emit(VerifyStart(seq=0, agent="TEMPER", target=target, status="fail", ts=0.0))
        emit(
            StepFail(
                seq=0,
                step=step,
                reason="Test discovery failed or returned invalid output",
                retry=0,
                ts=0.0,
            )
        )
        return "fail"
    if command is None:
        emit(VerifyStart(seq=0, agent="TEMPER", target=target, status="unverified", ts=0.0))
        return "unverified"
    emit(VerifyStart(seq=0, agent="TEMPER", target=target, status="running", ts=0.0))
    envelope = registry.dispatch("bash", {"cmd": command, "timeout_s": 120.0})
    result = envelope.get("result") or {}
    code = result.get("exit")
    output = "\n".join(
        "\n".join(
            str(result.get(k) or "") for k in ("stdout", "stderr") if result.get(k)
        ).splitlines()[-50:]
    )[-8192:]
    evidence = {"command": command, "exit_code": code, "output_tail": output}
    if envelope.get("ok") and type(code) is int and code == 0:
        emit(StepPass(seq=0, step=step, checks=[command], evidence=evidence, ts=0.0))
        return "pass"
    reason = str(
        envelope.get("error") or ("test timed out" if code == 124 else f"test exited {code}")
    )[:300]
    emit(StepFail(seq=0, step=step, reason=reason, retry=0, evidence=evidence, ts=0.0))
    return "fail"


def main(argv: list[str]) -> int:
    """`python -m arcen.agents.temper` — adversarial demo, NDJSON on stdout.

    Plants a broken assertion, verifies it (expect step.fail), fixes it,
    verifies again (expect step.pass). The demo IS the binary contract.
    """
    registry = load_builtin()
    temper = TemperVerifier(registry, adversarial=True, reruns=1)

    planted = (
        "mkdir -p /tmp/arcen_temper_demo && "
        "printf 'def add(a, b):\\n    return a + b\\n' > /tmp/arcen_temper_demo/calc.py && "
        "printf 'from calc import add\\ndef test_add():\\n    assert add(2, 2) == 5\\n' "
        "> /tmp/arcen_temper_demo/test_bad.py"
    )
    registry.dispatch("bash", {"cmd": planted})
    events = temper.verify(
        step=1,
        target="/tmp/arcen_temper_demo",
        checks=["python3 -m pytest -q /tmp/arcen_temper_demo/test_bad.py"],
    )
    fail_seen = events[-1].TYPE == "step.fail"

    fixed = (
        "printf 'from calc import add\\ndef test_add():\\n    assert add(2, 2) == 4\\n' "
        "> /tmp/arcen_temper_demo/test_bad.py"
    )
    registry.dispatch("bash", {"cmd": fixed})
    events = temper.verify(
        step=2,
        target="/tmp/arcen_temper_demo",
        checks=["python3 -m pytest -q /tmp/arcen_temper_demo/test_bad.py"],
    )
    pass_seen = events[-1].TYPE == "step.pass"

    registry.dispatch("bash", {"cmd": "rm -rf /tmp/arcen_temper_demo"})

    for e in [*events]:
        print(to_line(e))
    return 0 if (fail_seen and pass_seen) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
