"""Explicit two-image portability comparisons; never an adoption gate.

Images, Docker daemon, callbacks, local configuration and review attestations
are trusted. Distinct local image IDs do not establish environment independence,
image safety, provider identity, authentic evidence or improvement.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from arcen.config import ArcenConfig

from .budget import SharedBudget
from .comparison import ReviewedComparison, run_reviewed_comparison
from .durable_budget import DurableBudget
from .probe_execution import _reviewed_config
from .resolver import HarnessError
from .store import HarnessStore

_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class PortabilityComparison:
    """Two independently judged, locally supplied comparisons; no decision."""

    image_ids: tuple[str, str]
    first: ReviewedComparison = field(repr=False)
    second: ReviewedComparison | None = field(repr=False)
    outcome: str
    adoption_authorized: bool = field(default=False, init=False)


def validate_image_ids(image_ids: tuple[str, str]) -> None:
    """Validate two distinct content-addressed local Docker image identifiers."""
    if (
        type(image_ids) is not tuple
        or len(image_ids) != 2
        or any(type(image) is not str or not _IMAGE_ID.fullmatch(image) for image in image_ids)
        or image_ids[0] == image_ids[1]
    ):
        raise HarnessError("two distinct local Docker image IDs are required")


def run_portability_comparison(
    store: HarnessStore,
    baseline_id: str,
    candidate_id: str,
    task: str,
    config: ArcenConfig,
    judge: Callable[[dict], str],
    *,
    image_ids: tuple[str, str],
    repo: str | Path,
    commit: str,
    budget: SharedBudget | DurableBudget,
    reviewed_inputs: bool = False,
    reviewed_judge_inputs: bool = False,
    reviewed_images: bool = False,
    max_model_calls_per_trial: int = 4,
    sensitive_values: tuple[str, ...] = (),
) -> PortabilityComparison:
    """Compare baseline/candidate on two reviewed local Docker image IDs.

    The two full comparisons share one budget, frozen provider configuration,
    task, commit, and equivalent Git archive bytes. They each re-archive the
    commit; a differing second archive is rejected before its first trial.
    Provider and judge callbacks can expose data and cost money. This function
    neither checks the active baseline nor writes a review, moves a ref or
    authorizes anything. Review and trust each image before calling it.
    """
    if (
        reviewed_inputs is not True
        or reviewed_judge_inputs is not True
        or reviewed_images is not True
    ):
        raise HarnessError("explicit review of inputs, judge exposure and both images is required")
    validate_image_ids(image_ids)
    if type(store) is not HarnessStore or type(budget) not in (SharedBudget, DurableBudget):
        raise HarnessError("portability comparison requires a store and shared budget")
    if type(budget) is DurableBudget and budget.store is not store:
        raise HarnessError("durable budget must use the same store")
    if not callable(judge):
        raise HarnessError("invalid judge callback")
    cfg = _reviewed_config(config, True)
    if cfg.sandbox.network != "none" or cfg.sandbox.backend not in ("auto", "docker"):
        raise HarnessError("portability comparison requires Docker with networking disabled")
    budget.checkpoint()
    first_config = cfg.model_copy(deep=True)
    second_config = cfg.model_copy(deep=True)
    first_config.sandbox.image, second_config.sandbox.image = image_ids
    first = run_reviewed_comparison(
        store,
        baseline_id,
        candidate_id,
        task,
        first_config,
        judge,
        repo=repo,
        commit=commit,
        reviewed_inputs=True,
        reviewed_judge_inputs=True,
        max_model_calls_per_trial=max_model_calls_per_trial,
        sensitive_values=sensitive_values,
        budget=budget,
    )
    if first.judgment is None:
        return PortabilityComparison(image_ids, first, None, "inconclusive")
    second = run_reviewed_comparison(
        store,
        baseline_id,
        candidate_id,
        task,
        second_config,
        judge,
        repo=repo,
        commit=commit,
        reviewed_inputs=True,
        reviewed_judge_inputs=True,
        max_model_calls_per_trial=max_model_calls_per_trial,
        sensitive_values=sensitive_values,
        budget=budget,
        expected_workspace_sha256=first.reference.workspace_sha256,
    )
    outcome = "compared" if second.judgment is not None else "inconclusive"
    return PortabilityComparison(image_ids, first, second, outcome)
