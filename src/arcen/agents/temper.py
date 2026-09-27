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
        tail = (result.get("stderr") or result.get("stdout") or envelope.get("error") or "").strip()[-300:]
        return {"ok": False, "check": check, "reason": tail, "duration_s": duration}

    def _emit(self, event: Event) -> None:
        if self.emit is not None:
            self.emit(event)


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
    events = temper.verify(step=2, target="/tmp/arcen_temper_demo", checks=["python3 -m pytest -q /tmp/arcen_temper_demo/test_bad.py"])
    pass_seen = events[-1].TYPE == "step.pass"

    registry.dispatch("bash", {"cmd": "rm -rf /tmp/arcen_temper_demo"})

    for e in [*events]:
        print(to_line(e))
    return 0 if (fail_seen and pass_seen) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
