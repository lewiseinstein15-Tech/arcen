"""The refinement loop: produce → verify → gate → refine → accept.

This is the agent-level reading of a Loop Transformer. GLM-5.4 re-runs a
weight-shared block over the same hidden state; here the "state" is a
candidate artifact (a plan, a patch, an answer) and the "block" is the
produce/verify pair, which costs tokens and tool calls instead of FLOPs.

Loop shape, one pass at a time:

1. **produce** a candidate and its observations (what was executed);
2. **verify** it against evidence (:mod:`arcen.reasoning.verify`);
3. **gate** the next move (:mod:`arcen.reasoning.gate`);
4. **refine** with the contradictions in hand, weighted by the gate;
5. **stop** on verification, budget exhaustion, no measurable gain, a
   request for evidence, or an error — always returning the best candidate
   seen, never the last one by default.

The loop is transport-agnostic: it emits no stream events itself, so the
frozen 17-type schema is untouched. Callers narrate from :class:`PassRecord`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from arcen.reasoning.gate import MODIFY, PRESERVE, REPLACE, REQUEST_INFO, UpdateGate
from arcen.reasoning.verify import Observation, Verdict, check_observations

# Termination reasons, in the order the loop checks them.
VERIFIED = "verified"
BUDGET_EXHAUSTED = "budget_exhausted"
NO_GAIN = "no_gain"
REQUESTED_INFO = "request_info"
PRESERVED = "preserved"
ERROR = "error"


@dataclass
class Candidate:
    """Something the loop can accept or replace. ``value`` is opaque."""

    value: Any
    claim: str = ""
    model: str | None = None


@dataclass
class PassOutput:
    """What one produce() call yielded."""

    candidate: Candidate
    observations: list[Observation] = field(default_factory=list)
    test_status: str | None = None
    tokens: int = 0


@dataclass(frozen=True)
class PassContext:
    """Handed to produce() so a refinement knows what to fix."""

    pass_no: int
    previous: Candidate | None
    contradictions: tuple[str, ...]
    write_weight: float


@dataclass(frozen=True)
class PassRecord:
    """One pass, as it happened. This is the audit trail."""

    index: int
    action: str
    write_weight: float
    ok: bool
    confidence: float
    contradictions: tuple[str, ...]
    duration_s: float
    tokens: int
    accepted: bool  # did this pass become the best candidate?
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "action": self.action,
            "write_weight": round(self.write_weight, 3),
            "ok": self.ok,
            "confidence": round(self.confidence, 3),
            "contradictions": list(self.contradictions),
            "duration_s": self.duration_s,
            "tokens": self.tokens,
            "accepted": self.accepted,
            "error": self.error,
        }


@dataclass
class LoopResult:
    """The accepted candidate plus everything it took to get there."""

    accepted: Candidate
    verdict: Verdict
    passes: list[PassRecord]
    termination: str
    tokens: int
    duration_s: float

    @property
    def pass_count(self) -> int:
        return len(self.passes)

    @property
    def refinements(self) -> int:
        """Passes after the first — the ones refinement actually bought."""
        return max(0, len(self.passes) - 1)

    def to_dict(self) -> dict:
        return {
            "termination": self.termination,
            "passes": [p.to_dict() for p in self.passes],
            "pass_count": self.pass_count,
            "refinements": self.refinements,
            "tokens": self.tokens,
            "duration_s": self.duration_s,
            "verdict": self.verdict.to_dict(),
        }


def _score(verdict: Verdict) -> tuple[int, float]:
    return (1 if verdict.ok else 0, verdict.confidence)


class RefinementLoop:
    """Bounded iterative refinement over verifiable candidates.

    ``produce`` is called once per pass and must return a :class:`PassOutput`.
    ``verify`` defaults to the deterministic observation checks. ``budget``
    is the number of *refinements* allowed after the first attempt; the
    complexity estimator produces it, and it is clamped by ``max_passes``.
    """

    def __init__(
        self,
        *,
        budget: int,
        gate: UpdateGate | None = None,
        verify: Callable[[str, PassOutput], Verdict] | None = None,
        on_pass: Callable[[PassRecord], None] | None = None,
        max_passes: int = 4,
        min_gain: float = 0.05,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if budget < 0:
            raise ValueError("budget must be >= 0")
        if max_passes < 1:
            raise ValueError("max_passes must be >= 1")
        self.budget = min(budget, max_passes - 1)
        self.max_passes = max_passes
        self.gate = gate or UpdateGate()
        self.verify = verify or (
            lambda goal, output: check_observations(
                goal,
                output.observations,
                test_status=output.test_status,
                claim=output.candidate.claim,
            )
        )
        self.on_pass = on_pass
        self.min_gain = min_gain
        self.clock = clock

    def run(self, produce: Callable[[PassContext], PassOutput], *, goal: str) -> LoopResult:
        started = self.clock()
        records: list[PassRecord] = []
        total_tokens = 0

        best: Candidate | None = None
        best_verdict: Verdict | None = None
        previous: Candidate | None = None
        contradictions: tuple[str, ...] = ()
        weight = 0.0
        no_gain_streak = 0
        termination = BUDGET_EXHAUSTED

        for index in range(self.max_passes):
            pass_started = self.clock()
            context = PassContext(
                pass_no=index,
                previous=previous,
                contradictions=contradictions,
                write_weight=weight,
            )
            try:
                output = produce(context)
            except Exception as exc:  # noqa: BLE001 — a failed pass rolls back
                records.append(
                    PassRecord(
                        index=index,
                        action=PRESERVE,
                        write_weight=0.0,
                        ok=False,
                        confidence=0.0,
                        contradictions=(),
                        duration_s=round(self.clock() - pass_started, 4),
                        tokens=0,
                        accepted=False,
                        error=f"{type(exc).__name__}: {exc}"[:300],
                    )
                )
                termination = ERROR
                break

            total_tokens += max(0, int(output.tokens))
            verdict = self.verify(goal, output)
            gain = 0.0 if best_verdict is None else verdict.confidence - best_verdict.confidence

            # Best-so-far, not last-write-wins: a refinement that makes things
            # worse must not silently become the answer.
            improved = best_verdict is None or _score(verdict) > _score(best_verdict)
            if improved:
                best, best_verdict = output.candidate, verdict
                no_gain_streak = 0
            else:
                no_gain_streak += 1

            decision = self.gate.decide(
                pass_no=index,
                verified=verdict.ok,
                confidence=verdict.confidence,
                contradictions=verdict.contradictions,
                gain=gain,
                evidenced=verdict.evidenced,
            )
            record = PassRecord(
                index=index,
                action=decision.action,
                write_weight=decision.write_weight,
                ok=verdict.ok,
                confidence=verdict.confidence,
                contradictions=verdict.contradictions,
                duration_s=round(self.clock() - pass_started, 4),
                tokens=max(0, int(output.tokens)),
                accepted=improved,
            )
            records.append(record)
            if self.on_pass is not None:
                self.on_pass(record)

            previous = output.candidate
            contradictions = verdict.contradictions
            weight = decision.write_weight

            if decision.action == PRESERVE:
                termination = VERIFIED if verdict.ok else PRESERVED
                break
            if decision.action == REQUEST_INFO:
                termination = REQUESTED_INFO
                break
            if index >= self.budget:
                termination = BUDGET_EXHAUSTED
                break
            if no_gain_streak >= 2:
                termination = NO_GAIN
                break
            if decision.action not in (MODIFY, REPLACE):
                termination = PRESERVED
                break

        assert best is not None and best_verdict is not None
        return LoopResult(
            accepted=best,
            verdict=best_verdict,
            passes=records,
            termination=termination,
            tokens=total_tokens,
            duration_s=round(self.clock() - started, 4),
        )
