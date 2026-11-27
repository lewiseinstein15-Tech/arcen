"""Gated progressive updates — the agent-level analogue of GLM-5.4's gates.

GLM-5.4 adds a learned per-token gate for each loop iteration so a candidate
update is written into the residual stream *in proportion* to how much the
model should trust it. Empirically the first pass writes conservatively
(small gates, global context being built) and the second pass opens up to
write full refinements.

There is no residual stream here and no learned gate. What is reproduced is
the *policy*: a refinement pass is never applied wholesale by default. It is
classified as preserve / modify / replace / request-evidence, and carries a
scalar ``write_weight`` saying how much of it the caller should apply. The
weight is a scheduling heuristic derived from verification evidence, and is
documented as such — it is not a probability and not a confidence estimate
from the model.
"""

from __future__ import annotations

from dataclasses import dataclass

PRESERVE = "preserve"  # keep the current candidate; refinement adds nothing
MODIFY = "modify"  # apply part of the refinement (weighted)
REPLACE = "replace"  # the candidate is contradicted; take the refinement whole
REQUEST_INFO = "request_info"  # no evidence exists; refine later, gather first

ACTIONS = (PRESERVE, MODIFY, REPLACE, REQUEST_INFO)


@dataclass(frozen=True)
class GateDecision:
    """What to do with a refinement, and how much of it to trust."""

    action: str
    write_weight: float  # 0.0 = discard the refinement, 1.0 = apply it whole
    reason: str

    def __post_init__(self) -> None:
        if self.action not in ACTIONS:
            raise ValueError(f"unknown gate action {self.action!r}; expected one of {ACTIONS}")
        if not 0.0 <= self.write_weight <= 1.0:
            raise ValueError("write_weight must be within [0, 1]")

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "write_weight": round(self.write_weight, 3),
            "reason": self.reason,
        }


class UpdateGate:
    """Decides whether a refinement pass is worth applying, and how much.

    Parameters mirror the observed behaviour of GLM's gates without claiming
    to learn anything:

    - ``first_pass_cap``: the most a *first* refinement may write. The first
      pass is still building context, so it is capped low by default.
    - ``later_pass_ramp``: added per completed pass, so later passes may
      write more once earlier evidence has accumulated.
    - ``confidence_floor``: below this, a contradicted candidate is replaced
      rather than patched — patching a fundamentally wrong answer keeps the
      error.
    - ``min_gain``: a verified candidate whose refinement improves confidence
      by less than this is preserved; more passes would be spent for nothing.
    """

    def __init__(
        self,
        *,
        first_pass_cap: float = 0.35,
        later_pass_ramp: float = 0.3,
        confidence_floor: float = 0.6,
        min_gain: float = 0.05,
    ) -> None:
        if not 0.0 <= first_pass_cap <= 1.0:
            raise ValueError("first_pass_cap must be within [0, 1]")
        if later_pass_ramp < 0:
            raise ValueError("later_pass_ramp must be >= 0")
        if not 0.0 <= confidence_floor <= 1.0:
            raise ValueError("confidence_floor must be within [0, 1]")
        if min_gain < 0:
            raise ValueError("min_gain must be >= 0")
        self.first_pass_cap = first_pass_cap
        self.later_pass_ramp = later_pass_ramp
        self.confidence_floor = confidence_floor
        self.min_gain = min_gain

    def decide(
        self,
        *,
        pass_no: int,
        verified: bool,
        confidence: float,
        contradictions: tuple[str, ...] | list[str] = (),
        gain: float = 0.0,
        retryable: bool = True,
        evidenced: bool = True,
    ) -> GateDecision:
        """Classify the next move for a candidate that was just verified.

        ``pass_no`` is zero-based: the decision *after* pass 0 governs
        whether pass 1 happens.
        """
        if pass_no < 0:
            raise ValueError("pass_no must be >= 0")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be within [0, 1]")
        contradictions = tuple(contradictions)

        if not retryable:
            return GateDecision(PRESERVE, 0.0, "terminal failure — no refinement can help")

        if not evidenced:
            # Nothing ran, so nothing can be concluded. Refining here would be
            # the model grading its own homework.
            return GateDecision(
                REQUEST_INFO,
                0.0,
                "no executable evidence — gather a check before refining",
            )

        if verified and not contradictions:
            if pass_no == 0 or gain < self.min_gain:
                return GateDecision(
                    PRESERVE, 0.0, "verified with no contradictions; further passes add no gain"
                )
            return GateDecision(PRESERVE, 0.0, "verified; refinement gain below threshold")

        if verified and contradictions:
            # Evidence passes the executable checks but contradicts a claim:
            # this is a partial truth, so patch rather than replace.
            return GateDecision(
                MODIFY,
                self._weight(pass_no, confidence),
                f"verified but {len(contradictions)} contradiction(s) remain",
            )

        if contradictions:
            if confidence < self.confidence_floor:
                return GateDecision(
                    REPLACE,
                    1.0,
                    f"contradicted with low confidence ({confidence:.2f}) — patch would keep the error",
                )
            return GateDecision(
                MODIFY,
                self._weight(pass_no, confidence),
                f"contradicted ({len(contradictions)}) but confidence holds ({confidence:.2f})",
            )

        # Nothing failed and nothing contradicts: there is no evidence at all.
        # Refining here would be the model grading its own homework.
        return GateDecision(
            REQUEST_INFO,
            0.0,
            "no executable evidence — gather a check before refining further",
        )

    def _weight(self, pass_no: int, confidence: float) -> float:
        """How much of a refinement to write.

        First pass: ``min(cap, 1 - confidence)`` — conservative. Later
        passes: add ``later_pass_ramp`` per pass, so accumulated evidence
        opens the gate. Capped at 1.0.
        """
        headroom = 1.0 - confidence
        if pass_no == 0:
            return min(self.first_pass_cap, headroom)
        return min(1.0, headroom + self.later_pass_ramp * pass_no)
