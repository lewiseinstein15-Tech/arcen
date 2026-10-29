"""Static candidate review policy; no adoption or runtime selection is enabled.

Comparison uses verified object content, never a model-supplied description.
Code-defined protected files cannot be relaxed through a candidate manifest.
This is an early second review layer, not the final policy/adoption gate.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from .editor import EDITABLE
from .manifest import default_manifest
from .resolver import HarnessError, HarnessResolver
from .store import HarnessStore

TIER_0 = frozenset({"guardrails/policy.yaml", "tools/registry.toml"})
TIER_1 = frozenset(
    {"prompts/system.md", "prompts/draft.md", "prompts/forge.md", "prompts/temper.md"}
)
TIER_2 = frozenset({"tool-guidance.md"})


class AdoptionUnavailable(HarnessError):
    """No candidate can be adopted until the real approval gates exist."""


@dataclass(frozen=True, slots=True)
class Review:
    baseline_id: str
    candidate_id: str
    changed_paths: tuple[str, ...]
    highest_tier: int
    human_review_required: bool = True
    adoption_available: bool = False


def review_candidate(store: HarnessStore, baseline_id: str, candidate_id: str) -> Review:
    """Check immutable core and candidate prompts; permit review, not adoption."""
    baseline = store.get_manifest(baseline_id)
    candidate = store.get_manifest(candidate_id)
    packaged = default_manifest()
    if candidate.model_pin != baseline.model_pin:
        raise HarnessError("candidate cannot change model pin")
    for path in TIER_0:
        if baseline.components[path] != packaged.components[path]:
            raise HarnessError(f"protected baseline component changed: {path}")
        if candidate.components[path] != packaged.components[path]:
            raise HarnessError(f"protected candidate component changed: {path}")
    changed = tuple(
        sorted(
            path
            for path in baseline.components
            if baseline.components[path] != candidate.components[path]
        )
    )
    if not changed:
        raise HarnessError("candidate makes no component changes")
    if any(path not in EDITABLE or path not in (TIER_1 | TIER_2) for path in changed):
        raise HarnessError("candidate changes an unknown or protected component")
    with tempfile.TemporaryDirectory(prefix="arcen-policy-review-") as directory:
        root = Path(directory)
        for path in EDITABLE:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(store.get_blob(candidate.components[path]))
        HarnessResolver(root).resolve()
    return Review(
        baseline_id, candidate_id, changed, 1 if any(path in TIER_1 for path in changed) else 2
    )


def adopt_candidate(store: HarnessStore, baseline_id: str, candidate_id: str) -> None:
    """Fail closed unconditionally; review is not permission to adopt."""
    raise AdoptionUnavailable(
        "adoption unavailable: human approval, canaries and policy gates are not implemented"
    )
