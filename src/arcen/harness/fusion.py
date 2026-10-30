"""Advisory-only fusion of a local review and a matching manual canary report.

These records are unsigned and can be fabricated. The result is not an
adoption gate, human authentication, or proof of safety or improvement.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .canary import CASES, CanaryFinding, CanaryReport
from .resolver import HarnessError
from .review import ReviewRecord

_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[0-9a-f]{32}\Z")
_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


@dataclass(frozen=True, slots=True)
class Advisory:
    outcome: str  # keep_baseline | further_review | needs_human
    basis: str
    adoption_authorized: bool = False


def assess(review: ReviewRecord, canary: CanaryReport, *, threshold: float = 0.8) -> Advisory:
    """Fuse matching, unauthenticated evidence; never authorize an adoption.

    A regression or inconclusive result overrides all favorable opinions. A
    passing canary only means both runs passed small public tests. Local human
    review takes precedence over the comparison; a pending review with a
    positive comparison always needs separate human inspection.
    """
    if (
        type(threshold) not in (float, int)
        or not math.isfinite(threshold)
        or not 0 <= threshold <= 1
    ):
        raise HarnessError("invalid advisory confidence threshold")
    if (
        type(review) is not ReviewRecord
        or type(review.id) is not str
        or not _ID.fullmatch(review.id)
        or review.source != "paired"
        or type(review.state) is not str
        or review.state not in {"pending", "approved", "rejected"}
        or type(review.created_at) is not int
        or review.created_at < 0
        or (
            review.state == "pending"
            and any(x is not None for x in (review.reviewer, review.note, review.decided_at))
        )
        or (
            review.state != "pending"
            and (
                type(review.reviewer) is not str
                or not review.reviewer.strip()
                or len(review.reviewer) > 80
                or type(review.note) is not str
                or len(review.note) > 512
                or type(review.decided_at) is not int
                or review.decided_at < review.created_at
            )
        )
        or type(review.baseline_id) is not str
        or not _HASH.fullmatch(review.baseline_id)
        or type(review.candidate_id) is not str
        or not _HASH.fullmatch(review.candidate_id)
        or review.baseline_id == review.candidate_id
        or type(review.commit) is not str
        or not _COMMIT.fullmatch(review.commit)
        or type(review.workspace_sha256) is not str
        or not _HASH.fullmatch(review.workspace_sha256)
        or type(review.judge_winner) is not str
        or review.judge_winner not in {"candidate", "reference", "tie"}
        or type(review.judge_confidence) not in (float, int)
        or not math.isfinite(review.judge_confidence)
        or not 0 <= review.judge_confidence <= 1
    ):
        raise HarnessError("invalid paired review for advisory")
    if (
        type(canary) is not CanaryReport
        or canary.baseline_id != review.baseline_id
        or canary.candidate_id != review.candidate_id
        or canary.commit != review.commit
        or canary.workspace_sha256 != review.workspace_sha256
        or type(canary.outcome) is not str
        or canary.outcome not in {"passed", "regression", "inconclusive"}
        or type(canary.findings) is not tuple
        or not 1 <= len(canary.findings) <= len(CASES)
    ):
        raise HarnessError("canary report does not match the paired review")
    for index, item in enumerate(canary.findings):
        if (
            type(item) is not CanaryFinding
            or item.case_id != CASES[index].id
            or type(item.reference) is not str
            or type(item.candidate) is not str
        ):
            raise HarnessError("invalid canary findings")
        if index < len(canary.findings) - 1 and (item.reference, item.candidate) != (
            "passed",
            "passed",
        ):
            raise HarnessError("invalid canary findings")
    last = canary.findings[-1]
    if (
        (
            canary.outcome == "passed"
            and (
                len(canary.findings) != len(CASES)
                or (last.reference, last.candidate) != ("passed", "passed")
            )
        )
        or (
            canary.outcome == "regression"
            and (last.reference, last.candidate) != ("passed", "failed")
        )
        or (
            canary.outcome == "inconclusive"
            and (last.reference, last.candidate)
            not in {("inconclusive", "not-run"), ("failed", "not-run"), ("passed", "inconclusive")}
        )
    ):
        raise HarnessError("canary result contradicts findings")
    if canary.outcome == "regression":
        return Advisory("keep_baseline", "canary_regression")
    if canary.outcome == "inconclusive":
        return Advisory("needs_human", "canary_inconclusive")
    if review.state == "rejected":
        return Advisory("keep_baseline", "local_rejection")
    if review.state == "approved":
        return Advisory("further_review", "local_approval_not_authenticated")
    if review.judge_confidence < threshold:
        return Advisory("needs_human", "comparison_low_confidence")
    if review.judge_winner in {"reference", "tie"}:
        return Advisory("keep_baseline", "comparison_no_candidate_preference")
    return Advisory("needs_human", "comparison_prefers_candidate")
