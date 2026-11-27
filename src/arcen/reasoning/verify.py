"""Independent verification — evidence first, opinion second.

A refinement loop that asks the same model "is this good?" and accepts the
answer is a loop that agrees with itself. Two rules keep that from happening
here:

1. **Deterministic checks decide.** Test status, whether a failed tool ran,
   whether the files the goal named were actually touched, and whether a
   numeric claim ("2 passed") appears in real output. These are computed
   from observations, not from a model.
2. **A model verdict can only downgrade.** :func:`combine` takes the
   conjunction of the deterministic and model verdicts. If the tests pass
   and a reviewer model finds a contradiction, the result is "not ok". The
   reverse never happens: a model saying "looks fine" cannot overrule a
   failed test.

``independent`` is reported honestly: it is True only when the reviewer ran
on a *different model* than the producer. A same-model review is still
useful (it is a fresh context with a strict rubric), but it is labelled as
what it is.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)
_PASSED_CLAIM = re.compile(r"(\d+)\s+(?:passed|tests? passed|checks? passed)", re.IGNORECASE)
_FILE_IN_GOAL = re.compile(
    r"[\w./-]+\.(?:py|ts|tsx|js|jsx|rs|go|java|c|h|cpp|json|toml|ya?ml|md)\b"
)


@dataclass(frozen=True)
class Observation:
    """One executed step's outcome, as the verifier sees it."""

    tool: str
    ok: bool
    detail: str = ""

    def to_dict(self) -> dict:
        return {"tool": self.tool, "ok": self.ok, "detail": self.detail[:2000]}


@dataclass(frozen=True)
class Verdict:
    """The outcome of verification, with the evidence that produced it."""

    ok: bool
    confidence: float
    contradictions: tuple[str, ...] = field(default_factory=tuple)
    evidence: dict[str, Any] = field(default_factory=dict)
    independent: bool = False
    source: str = "deterministic"
    # True when a check actually ran (pass or fail). "Unverified" with no
    # failing observation is an absence of evidence, and the gate must not
    # treat it as a contradiction to be repaired.
    evidenced: bool = False

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "confidence": round(self.confidence, 3),
            "contradictions": list(self.contradictions),
            "evidence": self.evidence,
            "independent": self.independent,
            "source": self.source,
            "evidenced": self.evidenced,
        }


def check_observations(
    goal: str,
    observations: list[Observation],
    *,
    test_status: str | None = None,
    claim: str = "",
) -> Verdict:
    """Deterministic verdict from what actually happened.

    ``test_status`` is TEMPER's discovery result: ``"pass"``, ``"fail"``,
    ``"unverified"`` or ``None``. Only ``"pass"`` starts from a positive
    prior; everything else starts negative and must be argued up — which it
    cannot be, because only evidence adds confidence and there is no
    evidence here.
    """
    contradictions: list[str] = []
    evidence: dict[str, Any] = {"tests": test_status or "unverified", "observations": len(observations)}

    evidenced = test_status in {"pass", "fail"}
    if test_status == "pass":
        confidence = 0.85
        ok = True
    elif test_status == "fail":
        confidence = 0.15
        ok = False
        contradictions.append("the test suite failed")
    else:
        confidence = 0.3
        ok = False

    # A failed step is direct evidence that the work is not done, whatever
    # the tests say about the rest of the tree.
    for obs in observations:
        if not obs.ok:
            evidenced = True  # a failed tool IS evidence, even without a suite
            detail = " ".join(obs.detail.split())[:200]
            contradictions.append(f"{obs.tool} failed: {detail}" if detail else f"{obs.tool} failed")

    # The goal names files; if nothing ever touched them, the claim of
    # completion has no basis.
    touched = " ".join(obs.detail for obs in observations)
    for name in sorted(set(_FILE_IN_GOAL.findall(goal))):
        if name not in touched:
            contradictions.append(f"goal names {name} but no observation touched it")

    # A numeric claim must be backed by output, not asserted.
    for count in _PASSED_CLAIM.findall(claim or ""):
        if f"{count} passed" not in touched:
            contradictions.append(f"claim cites {count} passed but no observation shows it")

    confidence = max(0.05, confidence - 0.15 * len(contradictions))
    if contradictions:
        ok = False
    evidence["contradiction_count"] = len(contradictions)
    return Verdict(
        ok=ok,
        confidence=confidence,
        contradictions=tuple(contradictions),
        evidence=evidence,
        independent=False,
        source="deterministic",
        evidenced=evidenced,
    )


_VERIFIER_RUBRIC = """You are TEMPER, an adversarial verifier. You did not write this work.

Goal:
{goal}

What was executed (tool, ok, detail):
{observations}

Claimed result:
{claim}

Judge only what the evidence supports. Reply with ONE JSON object and nothing else:
{{"ok": true|false, "confidence": 0.0-1.0, "contradictions": ["..."]}}

Rules:
- A claim the observations do not support is a contradiction.
- Missing evidence is not proof of success; lower confidence instead.
- Do not restate the goal as evidence.
"""


def llm_verdict(
    client: Any,
    *,
    goal: str,
    observations: list[Observation],
    claim: str,
    producer_model: str | None = None,
    max_observation_chars: int = 1200,
) -> Verdict | None:
    """Ask a reviewer model for a structured verdict.

    Returns ``None`` when the model is unavailable or replies malformed —
    an unparseable review is no evidence, and must never be read as a pass.
    """
    if client is None:
        return None

    rendered = "\n".join(
        f"- {obs.tool} ok={obs.ok}: {' '.join(obs.detail.split())[:max_observation_chars]}"
        for obs in observations
    ) or "- (nothing executed)"
    prompt = _VERIFIER_RUBRIC.format(goal=goal[:2000], observations=rendered, claim=(claim or "")[:2000])

    try:
        response = client.complete(
            "verifier", [{"role": "user", "content": prompt}], temperature=0.0
        )
    except Exception:  # noqa: BLE001 — a failed review is no review, never a pass
        return None

    match = _JSON_BLOCK.search(getattr(response, "text", "") or "")
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(parsed, dict) or not isinstance(parsed.get("ok"), bool):
        return None

    raw_confidence = parsed.get("confidence", 0.0)
    if isinstance(raw_confidence, bool) or not isinstance(raw_confidence, (int, float)):
        raw_confidence = 0.0
    confidence = min(1.0, max(0.0, float(raw_confidence)))

    raw_contradictions = parsed.get("contradictions") or []
    if not isinstance(raw_contradictions, list):
        raw_contradictions = []
    contradictions = tuple(str(item)[:300] for item in raw_contradictions[:8])

    independent = False
    if producer_model:
        try:
            independent = client.model_for("verifier") != producer_model
        except Exception:  # noqa: BLE001 — unknown model is reported as not independent
            independent = False

    return Verdict(
        ok=bool(parsed["ok"]),
        confidence=confidence,
        contradictions=contradictions,
        evidence={"review_model": getattr(response, "model", "")},
        independent=independent,
        source="llm",
        evidenced=bool(observations),
    )


def combine(deterministic: Verdict, reviewed: Verdict | None) -> Verdict:
    """Conjoin a deterministic verdict with a model review.

    The review may add contradictions and lower confidence. It may never
    turn a deterministic failure into a pass.
    """
    if reviewed is None:
        return deterministic

    contradictions = deterministic.contradictions + tuple(
        c for c in reviewed.contradictions if c not in deterministic.contradictions
    )
    return Verdict(
        ok=deterministic.ok and reviewed.ok,
        confidence=min(deterministic.confidence, reviewed.confidence),
        contradictions=contradictions,
        evidence={**deterministic.evidence, "review": reviewed.evidence},
        independent=reviewed.independent,
        source=f"{deterministic.source}+{reviewed.source}",
        evidenced=deterministic.evidenced or reviewed.evidenced,
    )
