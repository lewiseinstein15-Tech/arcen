"""Conservative advisory fusion; never an adoption or safety decision."""

from __future__ import annotations

from dataclasses import replace

import pytest

from arcen.harness.canary import CASES, CanaryFinding, CanaryReport
from arcen.harness.fusion import Advisory, assess
from arcen.harness.resolver import HarnessError
from arcen.harness.review import ReviewRecord

BASE, CANDIDATE, WORKSPACE, COMMIT = "a" * 64, "b" * 64, "c" * 64, "d" * 40


def review(**changes):
    return replace(
        ReviewRecord(
            id="f" * 32,
            baseline_id=BASE,
            candidate_id=CANDIDATE,
            source="paired",
            commit=COMMIT,
            workspace_sha256=WORKSPACE,
            judge_winner="candidate",
            judge_confidence=0.9,
            state="pending",
            created_at=1,
            reviewer=None,
            note=None,
            decided_at=None,
        ),
        **changes,
    )


def report(outcome="passed"):
    findings = [CanaryFinding(case.id, "passed", "passed") for case in CASES]
    if outcome == "regression":
        findings[-1] = CanaryFinding(CASES[-1].id, "passed", "failed")
    elif outcome == "inconclusive":
        findings[-1] = CanaryFinding(CASES[-1].id, "passed", "inconclusive")
    return CanaryReport(BASE, CANDIDATE, COMMIT, WORKSPACE, outcome, tuple(findings))


def decided(state, **changes):
    return review(state=state, reviewer="local", note="", decided_at=2, **changes)


@pytest.mark.parametrize("state", ["pending", "approved", "rejected"])
def test_regression_and_inconclusive_override_all_opinions(state):
    record = review() if state == "pending" else decided(state)
    assert assess(record, report("regression")) == Advisory("keep_baseline", "canary_regression")
    assert assess(record, report("inconclusive")) == Advisory("needs_human", "canary_inconclusive")
    assert assess(record, report("regression")).adoption_authorized is False


def test_human_record_precedes_comparison_but_never_authorizes():
    assert assess(decided("approved", judge_winner="reference"), report()) == Advisory(
        "further_review", "local_approval_not_authenticated"
    )
    assert assess(decided("rejected", judge_winner="candidate"), report()) == Advisory(
        "keep_baseline", "local_rejection"
    )


def test_pending_comparison_respects_confidence_and_never_auto_adopts():
    assert assess(review(judge_confidence=0.79), report()).basis == "comparison_low_confidence"
    assert assess(review(judge_confidence=0.8), report()).outcome == "needs_human"
    assert assess(review(judge_winner="reference"), report()).outcome == "keep_baseline"
    assert assess(review(judge_winner="tie"), report()).outcome == "keep_baseline"
    assert (
        assess(review(judge_winner="tie", judge_confidence=0.1), report()).outcome == "needs_human"
    )
    assert not assess(review(), report()).adoption_authorized


@pytest.mark.parametrize("field", ["baseline_id", "candidate_id", "workspace_sha256", "commit"])
def test_inconsistent_identity_or_snapshot_fails_closed(field):
    wrong = "e" * (40 if field == "commit" else 64)
    with pytest.raises(HarnessError, match="does not match"):
        assess(review(), replace(report(), **{field: wrong}))


@pytest.mark.parametrize("threshold", [True, -1, 1.1, float("nan"), float("inf"), "0.8"])
def test_invalid_confidence_threshold_fails_closed(threshold):
    with pytest.raises(HarnessError, match="threshold"):
        assess(review(), report(), threshold=threshold)


@pytest.mark.parametrize("invalid", [True, -1, 2, float("nan"), None])
def test_invalid_stored_judge_confidence_fails_closed(invalid):
    with pytest.raises(HarnessError, match="invalid paired review"):
        assess(review(judge_confidence=invalid), report())


def test_contradictory_or_incomplete_canary_report_cannot_pass():
    good = report()
    bad = [
        replace(good, findings=()),
        replace(good, findings=good.findings[:1]),
        replace(good, outcome="regression"),
        replace(good, outcome="inconclusive"),
        replace(good, findings=(CanaryFinding("not-a-case", "passed", "passed"),)),
        replace(
            good, findings=(CanaryFinding(CASES[0].id, "failed", "not-run"), good.findings[-1])
        ),
        replace(good, findings=(CanaryFinding(CASES[0].id, [], "passed"), good.findings[-1])),
    ]
    for value in bad:
        with pytest.raises(HarnessError):
            assess(review(), value)


def test_forged_state_missing_reviewer_is_structurally_rejected():
    with pytest.raises(HarnessError):
        assess(review(state="approved"), report())
    with pytest.raises(HarnessError):
        assess(review(state="pending", reviewer="someone"), report())
