"""Compose reviewed proposals and optionally compare them; never adopt."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from arcen.config import ArcenConfig

from .comparison import ReviewedComparison, run_reviewed_comparison
from .composer import Composition, compose_proposals
from .editor import Proposal
from .resolver import HarnessError
from .store import HarnessStore


@dataclass(frozen=True, slots=True)
class ProposalComparison:
    composition: Composition
    comparison: ReviewedComparison | None = field(repr=False)


def compare_reviewed_proposals(
    store: HarnessStore,
    baseline_id: str,
    proposals: tuple[Proposal, ...],
    task: str,
    config: ArcenConfig,
    judge: Callable[[dict], str],
    *,
    repo: str | Path,
    commit: str,
    reviewed_inputs: bool = False,
    reviewed_judge_inputs: bool = False,
    max_model_calls_per_trial: int = 4,
    sensitive_values: tuple[str, ...] = (),
) -> ProposalComparison:
    """Compose, trial twice, and judge; conflicts stop before any probe.

    Both review attestations include the proposed edits and combined prompt
    content. This function never moves a ref or authorizes adoption. On later
    failures, immutable unreferenced candidate objects may remain in the store.
    """
    if reviewed_inputs is not True or reviewed_judge_inputs is not True:
        raise HarnessError("explicit review of proposals, probe and judge inputs is required")
    if not callable(judge):
        raise HarnessError("invalid judge callback")
    composition = compose_proposals(store, baseline_id, proposals)
    if composition.candidate_id is None:
        return ProposalComparison(composition, None)
    comparison = run_reviewed_comparison(
        store,
        baseline_id,
        composition.candidate_id,
        task,
        config,
        judge,
        repo=repo,
        commit=commit,
        reviewed_inputs=True,
        reviewed_judge_inputs=True,
        max_model_calls_per_trial=max_model_calls_per_trial,
        sensitive_values=sensitive_values,
    )
    return ProposalComparison(composition, comparison)
