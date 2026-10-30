"""Manually initiated, bounded sequential comparisons; no adoption or resume.

The caller reviews every candidate, workspace and provider exposure before
invoking this trusted Python API. It runs no editor and selects no winner.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from arcen.config import ArcenConfig

from .budget import BudgetExhausted, SharedBudget
from .campaign_journal import CampaignJournal, CampaignStopped
from .comparison import ReviewedComparison
from .judge import Trajectory, compare
from .policy import review_candidate
from .probe import ProbeUnavailable
from .probe_execution import ReviewedProbeResult, _reviewed_config, _run_bound_probe
from .probe_model import bind_probe_model
from .probe_workspace import snapshot_git_commit
from .resolver import HarnessError
from .review import ReviewLedger, ReviewRecord
from .store import HarnessStore

MAX_CANDIDATES = 5


@dataclass(frozen=True, slots=True)
class CampaignItem:
    candidate_id: str
    comparison: ReviewedComparison = field(repr=False)
    review: ReviewRecord


@dataclass(frozen=True, slots=True)
class ManualCampaignResult:
    reference: ReviewedProbeResult | None = field(repr=False)
    completed: tuple[CampaignItem, ...]
    stop_reason: str | None
    stopped_candidate: str | None


def run_manual_campaign(
    store: HarnessStore,
    baseline_id: str,
    candidates: tuple[str, ...],
    task: str,
    config: ArcenConfig,
    judge: Callable[[dict], str],
    *,
    repo: str | Path,
    commit: str,
    reviews: ReviewLedger,
    budget: SharedBudget,
    reviewed_inputs: bool = False,
    reviewed_judge_inputs: bool = False,
    max_model_calls_per_trial: int = 4,
    sensitive_values: tuple[str, ...] = (),
    journal: CampaignJournal | None = None,
    campaign_id: str | None = None,
) -> ManualCampaignResult:
    """Compare reviewed candidates with one reference trial, sequentially.

    A successful comparison creates a *pending* local review request. On any
    execution, judge or review-record error, stop with completed items retained.
    This API never selects a winner, authorizes execution, moves a ref or adopts.
    """
    if reviewed_inputs is not True or reviewed_judge_inputs is not True:
        raise HarnessError("explicit review of campaign and judge inputs is required")
    if (
        type(store) is not HarnessStore
        or type(reviews) is not ReviewLedger
        or reviews.store is not store
    ):
        raise HarnessError("campaign requires a review ledger for the same store")
    if type(budget) is not SharedBudget:
        raise HarnessError("campaign requires a shared budget")
    if (journal is None) != (campaign_id is None) or (
        journal is not None and (type(journal) is not CampaignJournal or journal.store is not store)
    ):
        raise HarnessError("campaign journal and ID must match the store")
    if (
        type(baseline_id) is not str
        or type(candidates) is not tuple
        or not 1 <= len(candidates) <= MAX_CANDIDATES
        or any(type(x) is not str for x in candidates)
        or len(set(candidates)) != len(candidates)
        or baseline_id in candidates
    ):
        raise HarnessError("campaign requires distinct candidate manifests")
    if not callable(judge):
        raise HarnessError("invalid judge callback")
    if (
        type(sensitive_values) is not tuple
        or len(sensitive_values) > 31
        or any(type(x) is not str or len(x) < 4 or len(x) > 256 for x in sensitive_values)
    ):
        raise HarnessError("invalid sensitive values")
    budget.checkpoint()
    cfg = _reviewed_config(config, True)
    key = cfg.provider.api_key
    if len(key) > 256:
        raise HarnessError("provider credential exceeds comparison redaction limit")
    hidden = tuple(dict.fromkeys((*sensitive_values, *((key,) if key else ()))))
    # All candidates and their prompt snapshots are preflighted before Git,
    # model calls, Docker creation, callback invocation or ledger writes.
    for candidate in candidates:
        review_candidate(store, baseline_id, candidate)
    reference_model = bind_probe_model(
        store,
        baseline_id,
        baseline_id,
        task,
        cfg,
        max_calls=max_model_calls_per_trial,
        budget=budget,
    )
    models = tuple(
        bind_probe_model(
            store,
            baseline_id,
            candidate,
            task,
            cfg,
            max_calls=max_model_calls_per_trial,
            budget=budget,
        )
        for candidate in candidates
    )
    budget.checkpoint()
    if journal is not None:
        journal.claim(campaign_id, baseline_id, candidates, task, commit)
    completed: list[CampaignItem] = []
    reference: ReviewedProbeResult | None = None

    def result(reason: str | None, candidate: str | None = None) -> ManualCampaignResult:
        if journal is not None and reason is not None:
            state = journal.get(campaign_id).state
            if state == "running":
                journal.fail(campaign_id)
                state = journal.get(campaign_id).state
            if state == "stopped":
                reason = "stopped"
        return ManualCampaignResult(reference, tuple(completed), reason, candidate)

    try:
        if journal is not None:
            journal.checkpoint(campaign_id, "reference", 0)
        snapshot = snapshot_git_commit(repo, commit)
        if journal is not None:
            journal.checkpoint(campaign_id, "reference", 0)
    except CampaignStopped:
        return result("stopped")
    except Exception:
        if journal is not None:
            journal.fail(campaign_id)
        raise

    try:
        reference = _run_bound_probe(snapshot, cfg, reference_model)
    except BudgetExhausted:
        return result("budget_closed")
    except ProbeUnavailable:
        return result("reference_isolation_failed")
    if reference.status != "ok":
        return result("budget_closed" if budget.snapshot().stopped else "reference_failed")
    try:
        if journal is not None:
            journal.advance(campaign_id, "reference", "candidate")
    except CampaignStopped:
        return result("stopped")

    for index, (candidate, model) in enumerate(zip(candidates, models, strict=True)):
        try:
            if journal is not None:
                journal.checkpoint(campaign_id, "candidate", index)
            trial = _run_bound_probe(snapshot, cfg, model)
        except CampaignStopped:
            return result("stopped", candidate)
        except BudgetExhausted:
            return result("budget_closed", candidate)
        except ProbeUnavailable:
            return result("candidate_isolation_failed", candidate)
        if trial.status != "ok":
            return result(
                "budget_closed" if budget.snapshot().stopped else "candidate_failed", candidate
            )
        try:
            if journal is not None:
                journal.advance(campaign_id, "candidate", "judge")
                journal.checkpoint(campaign_id, "judge", index)
        except CampaignStopped:
            return result("stopped", candidate)

        def limited_judge(request):
            budget.reserve_judge_call()
            return judge(request)

        try:
            judgment = compare(
                task,
                Trajectory(baseline_id, reference.events),
                Trajectory(candidate, trial.events),
                limited_judge,
                sensitive_values=hidden,
            )
        except Exception:  # noqa: BLE001 — never expose callback/provider details
            return result(
                "budget_closed" if budget.snapshot().stopped else "judge_failed", candidate
            )
        pair = ReviewedComparison(reference, trial, judgment)
        try:
            if journal is not None:
                journal.advance(campaign_id, "judge", "recording")
                journal.checkpoint(campaign_id, "recording", index)
            budget.checkpoint()
            review = reviews.request_from_comparison(pair)
        except CampaignStopped:
            return result("stopped", candidate)
        except BudgetExhausted:
            return result("budget_closed", candidate)
        except Exception:  # noqa: BLE001 — no further work after ledger failure
            return result("review_record_failed", candidate)
        completed.append(CampaignItem(candidate, pair, review))
        if journal is not None:
            state = journal.record_review(campaign_id, candidate, review.id)
            if state.state == "stopped":
                return result("stopped", candidate)
    return result(None)
