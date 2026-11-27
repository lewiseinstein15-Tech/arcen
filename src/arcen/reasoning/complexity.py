"""Task complexity → reasoning budget.

GLM-5.4's gates adjust their step size per token, so hard predictions get
more iterative refinement than easy ones. At the agent level the analogous
decision happens *before* any tokens are spent: how many verification /
refinement passes is this goal worth?

The estimator is deliberately deterministic — a lexical heuristic, not a
model call. Two reasons: it costs nothing, and it can be unit-tested and
audited, which a "the model decided it was hard" signal cannot. The cost is
that it is coarse. It is a budget allocator, not a difficulty oracle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Weighted signals. Each hit adds its weight to the score; the thresholds
# below turn the score into a budget. Values were chosen so that a
# self-contained one-file task lands at "simple" and a multi-stage
# repository change lands at "complex".
_SIGNALS: tuple[tuple[re.Pattern[str], float, str], ...] = (
    (re.compile(r"\b(?:refactor|migrat|architecture|architect|redesign|rewrite)\w*", re.IGNORECASE), 1.0,
     "structural change"),
    (re.compile(r"\b(?:repository|repo|codebase|module|package|monorepo)\b", re.IGNORECASE), 0.8,
     "repository-scale scope"),
    (re.compile(r"\b(?:test|pytest|spec|assert|coverage)\w*", re.IGNORECASE), 0.6, "test requirement"),
    (re.compile(r"\b(?:debug|fix|traceback|failing|regression|bug)\w*", re.IGNORECASE), 0.6,
     "debugging"),
    (re.compile(r"\b(?:prove|theorem|derive|integral|derivative|matrix|optimi[sz]e)\w*", re.IGNORECASE),
     0.9, "mathematical reasoning"),
    (re.compile(r"\b(?:simulate|simulation|numerical|monte carlo|differential)\w*", re.IGNORECASE), 0.9,
     "scientific computation"),
    (re.compile(r"\b(?:3d|cad|freecad|shader|glsl|geometry|render|animation|video)\b", re.IGNORECASE), 0.8,
     "graphics/geometry"),
    (re.compile(r"\b(?:and then|after that|followed by|then run|then verify|finally)\b", re.IGNORECASE), 0.5,
     "multi-stage chain"),
    (re.compile(r"\b(?:step \d|first,|second,|third,)\b", re.IGNORECASE), 0.4, "enumerated steps"),
)

# A goal naming several files is wider than one naming a single file.
_FILE_PATTERN = re.compile(r"[\w./-]+\.(?:py|ts|tsx|js|jsx|rs|go|java|c|h|cpp|json|toml|ya?ml|md)\b")

# Long goals describe more surface area than short ones.
_LONG_GOAL_CHARS = 220
_VERY_LONG_GOAL_CHARS = 500


@dataclass(frozen=True)
class Complexity:
    """The budget a goal earns, with the reasons that produced it."""

    level: str  # "simple" | "moderate" | "complex"
    score: float
    budget: int  # refinement passes allowed after the first pass (0..max_passes)
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "score": round(self.score, 3),
            "budget": self.budget,
            "reasons": list(self.reasons),
        }


def estimate_complexity(goal: str, *, max_passes: int = 3) -> Complexity:
    """Score ``goal`` and return a bounded refinement budget.

    ``max_passes`` caps the result so a config change (or a pathological
    goal) can never request unbounded refinement. A budget of 0 means "one
    attempt, no refinement" — the simple-task default.
    """
    if max_passes < 1:
        raise ValueError("max_passes must be >= 1")

    text = goal.strip()
    score = 0.0
    reasons: list[str] = []

    for pattern, weight, label in _SIGNALS:
        if pattern.search(text):
            score += weight
            reasons.append(label)

    files = set(_FILE_PATTERN.findall(text))
    if len(files) >= 2:
        score += 0.5
        reasons.append(f"{len(files)} files named")
    elif len(files) == 1:
        score += 0.2

    if len(text) >= _VERY_LONG_GOAL_CHARS:
        score += 0.6
        reasons.append("very long goal")
    elif len(text) >= _LONG_GOAL_CHARS:
        score += 0.3
        reasons.append("long goal")

    # Conjunctions chain independent outcomes; each extra clause adds work.
    clauses = len(re.findall(r"[;,]", text)) + text.lower().count(" and ")
    if clauses >= 3:
        score += 0.4
        reasons.append("many clauses")

    if score >= 2.0:
        level, wanted = "complex", 3
    elif score >= 0.8:
        level, wanted = "moderate", 2
    else:
        level, wanted = "simple", 1

    # budget counts refinement passes after the first attempt.
    budget = min(wanted - 1, max_passes - 1)
    return Complexity(level=level, score=score, budget=max(0, budget), reasons=tuple(reasons))
