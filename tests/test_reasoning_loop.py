"""The refinement loop must terminate, and must never accept a worse answer.

These pin the properties that make an iterative reasoning loop safe to leave
running: bounded passes, best-so-far acceptance, rollback on a failed pass,
and a gate that refuses to refine when there is no evidence to refine
against.
"""

from __future__ import annotations

import pytest

from arcen.reasoning import (
    MODIFY,
    PRESERVE,
    REPLACE,
    REQUEST_INFO,
    Candidate,
    Observation,
    PassOutput,
    RefinementLoop,
    UpdateGate,
    check_observations,
    estimate_complexity,
)
from arcen.reasoning.gate import GateDecision


def _output(ok: bool, confidence: float, detail: str = "", claim: str = "") -> PassOutput:
    return PassOutput(
        candidate=Candidate(value=detail or ("ok" if ok else "bad"), claim=claim),
        observations=[Observation(tool="bash", ok=ok, detail=detail)],
        test_status="pass" if ok else "fail",
    )


# -- complexity -------------------------------------------------------------


def test_simple_goal_earns_no_refinement() -> None:
    result = estimate_complexity("say hello")
    assert result.level == "simple"
    assert result.budget == 0


def test_repository_scale_goal_earns_refinements() -> None:
    result = estimate_complexity(
        "refactor the repository architecture, migrate the database, and then run the "
        "full pytest suite until every failing regression passes"
    )
    assert result.level == "complex"
    assert result.budget >= 1


def test_budget_is_capped_by_max_passes() -> None:
    result = estimate_complexity("refactor repository architecture and migrate tests", max_passes=2)
    assert result.budget <= 1


def test_estimate_is_deterministic() -> None:
    goal = "debug the failing test in calc.py and then verify with pytest"
    assert estimate_complexity(goal) == estimate_complexity(goal)


def test_zero_max_passes_is_rejected() -> None:
    with pytest.raises(ValueError):
        estimate_complexity("anything", max_passes=0)


# -- gate -------------------------------------------------------------------


def test_gate_preserves_a_verified_candidate() -> None:
    decision = UpdateGate().decide(pass_no=0, verified=True, confidence=0.9)
    assert decision.action == PRESERVE
    assert decision.write_weight == 0.0


def test_gate_replaces_a_contradicted_low_confidence_candidate() -> None:
    decision = UpdateGate(confidence_floor=0.6).decide(
        pass_no=0, verified=False, confidence=0.2, contradictions=("test failed",)
    )
    assert decision.action == REPLACE
    assert decision.write_weight == 1.0


def test_gate_modifies_a_contradicted_confident_candidate() -> None:
    decision = UpdateGate(confidence_floor=0.6).decide(
        pass_no=1, verified=False, confidence=0.8, contradictions=("one check failed",)
    )
    assert decision.action == MODIFY
    assert 0.0 < decision.write_weight <= 1.0


def test_gate_refuses_to_refine_without_evidence() -> None:
    decision = UpdateGate().decide(pass_no=0, verified=False, confidence=0.3)
    assert decision.action == REQUEST_INFO
    assert decision.write_weight == 0.0


def test_first_pass_writes_conservatively_and_later_passes_open_up() -> None:
    gate = UpdateGate(first_pass_cap=0.35, later_pass_ramp=0.3)
    first = gate.decide(pass_no=0, verified=False, confidence=0.8, contradictions=("x",))
    later = gate.decide(pass_no=2, verified=False, confidence=0.8, contradictions=("x",))
    assert first.write_weight <= 0.35
    assert later.write_weight > first.write_weight


def test_gate_rejects_out_of_range_weight() -> None:
    with pytest.raises(ValueError):
        GateDecision(action=MODIFY, write_weight=1.5, reason="bad")


# -- verifier ---------------------------------------------------------------


def test_verifier_flags_a_file_the_goal_named_but_nothing_touched() -> None:
    verdict = check_observations(
        "create calc.py with add()",
        [Observation(tool="bash", ok=True, detail="echo hi")],
        test_status="pass",
    )
    assert verdict.ok is False
    assert any("calc.py" in c for c in verdict.contradictions)


def test_verifier_accepts_work_that_touched_the_named_file() -> None:
    verdict = check_observations(
        "create calc.py with add()",
        [Observation(tool="file.write", ok=True, detail="/workspace/calc.py written")],
        test_status="pass",
    )
    assert verdict.ok is True
    assert verdict.confidence >= 0.8


def test_verifier_treats_unverified_as_not_ok() -> None:
    verdict = check_observations("do something", [], test_status="unverified")
    assert verdict.ok is False
    assert verdict.confidence < 0.5


def test_verifier_rejects_an_uncorroborated_numeric_claim() -> None:
    verdict = check_observations(
        "run the tests",
        [Observation(tool="bash", ok=True, detail="collected 2 items")],
        test_status="pass",
        claim="all good, 7 passed",
    )
    assert verdict.ok is False
    assert any("7 passed" in c for c in verdict.contradictions)


def test_failed_observation_is_always_a_contradiction() -> None:
    verdict = check_observations(
        "run the tests",
        [Observation(tool="bash", ok=False, detail="ImportError: no module named calc")],
        test_status="pass",
    )
    assert verdict.ok is False
    assert any("ImportError" in c for c in verdict.contradictions)


# -- loop -------------------------------------------------------------------


def test_loop_stops_after_one_pass_when_verification_succeeds() -> None:
    calls: list[int] = []

    def produce(ctx):
        calls.append(ctx.pass_no)
        return _output(True, 0.9, detail="/workspace/calc.py written (12 bytes)")

    result = RefinementLoop(budget=2).run(produce, goal="write calc.py")
    assert calls == [0]
    assert result.termination == "verified"
    assert result.pass_count == 1
    assert result.verdict.ok is True


def test_loop_refines_after_a_failure_and_accepts_the_fix() -> None:
    def produce(ctx):
        if ctx.pass_no == 0:
            return _output(False, 0.2, detail="calc.py AssertionError: 3 != 4")
        assert ctx.contradictions, "refinement must receive the failure evidence"
        return _output(True, 0.85, detail="calc.py 2 passed")

    result = RefinementLoop(budget=2).run(produce, goal="fix the failing test in calc.py")
    assert result.pass_count == 2
    assert result.verdict.ok is True
    assert result.refinements == 1


def test_loop_never_accepts_a_worse_candidate() -> None:
    def produce(ctx):
        if ctx.pass_no == 0:
            return _output(True, 0.9, detail="good")
        return _output(False, 0.1, detail="worse")

    result = RefinementLoop(budget=3).run(produce, goal="x")
    assert result.accepted.value == "good"
    assert result.verdict.ok is True


def test_loop_respects_the_budget() -> None:
    def produce(ctx):
        return _output(False, 0.5, detail="still broken")

    result = RefinementLoop(budget=1).run(produce, goal="x")
    assert result.pass_count == 2
    assert result.termination == "budget_exhausted"


def test_loop_rolls_back_when_a_pass_raises() -> None:
    def produce(ctx):
        if ctx.pass_no == 0:
            return _output(False, 0.4, detail="first attempt")
        raise RuntimeError("provider died mid-refinement")

    result = RefinementLoop(budget=2).run(produce, goal="x")
    assert result.termination == "error"
    assert result.accepted.value == "first attempt"
    assert result.passes[-1].error and "provider died" in result.passes[-1].error


def test_loop_stops_requesting_evidence_instead_of_guessing() -> None:
    def produce(ctx):
        return PassOutput(candidate=Candidate(value="v"), observations=[], test_status="unverified")

    result = RefinementLoop(budget=3).run(produce, goal="x")
    assert result.pass_count == 1
    assert result.termination == "request_info"


def test_loop_reports_every_pass_for_audit() -> None:
    seen = []

    def produce(ctx):
        return _output(False, 0.4, detail="broken")

    RefinementLoop(budget=1, on_pass=seen.append).run(produce, goal="x")
    assert [p.index for p in seen] == [0, 1]
    assert all(p.action in {PRESERVE, MODIFY, REPLACE, REQUEST_INFO} for p in seen)
