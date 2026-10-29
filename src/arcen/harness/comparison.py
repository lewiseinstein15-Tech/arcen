"""Explicitly reviewed paired trials and a blinded callback judge.

This is a bounded experimental API, not a campaign, adoption gate or proof of
improvement. All local inputs and the judge callback are trusted by the caller.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from arcen.config import ArcenConfig

from .budget import SharedBudget
from .judge import Judgment, Trajectory, compare
from .probe import ProbeUnavailable
from .probe_execution import ReviewedProbeResult, _reviewed_config, _run_bound_probe
from .probe_model import bind_probe_model
from .probe_workspace import snapshot_git_commit
from .resolver import HarnessError
from .store import HarnessStore


@dataclass(frozen=True, slots=True)
class ReviewedComparison:
    reference: ReviewedProbeResult = field(repr=False)
    candidate: ReviewedProbeResult | None = field(repr=False)
    judgment: Judgment | None


def run_reviewed_comparison(
    store: HarnessStore,
    baseline_id: str,
    candidate_id: str,
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
    budget: SharedBudget | None = None,
) -> ReviewedComparison:
    """Run two fresh trials over one snapshot, then judge reduced evidence.

    The caller must separately attest review of provider and judge exposure.
    Trials and the optional callback can transmit data and incur cost. A trial
    error returns no judgment. Neither the result nor the judgment adopts code.
    """
    if reviewed_inputs is not True or reviewed_judge_inputs is not True:
        raise HarnessError("explicit review of probe and judge inputs is required")
    if type(baseline_id) is not str or type(candidate_id) is not str or baseline_id == candidate_id:
        raise HarnessError("comparison requires distinct baseline and candidate manifests")
    if budget is not None and type(budget) is not SharedBudget:
        raise HarnessError("invalid shared budget")
    if not callable(judge):
        raise HarnessError("invalid judge callback")
    if (
        type(sensitive_values) is not tuple
        or len(sensitive_values) > 31
        or any(type(x) is not str or len(x) < 4 or len(x) > 256 for x in sensitive_values)
    ):
        raise HarnessError("invalid sensitive values")
    cfg = _reviewed_config(config, True)
    key = cfg.provider.api_key
    if len(key) > 256:
        raise HarnessError("provider credential exceeds comparison redaction limit")
    hidden = tuple(dict.fromkeys((*sensitive_values, *((key,) if key else ()))))
    # Preflight both candidates and freeze both provider bridges before a model
    # request or workspace execution. The same config and task are used for each.
    reference_model = bind_probe_model(
        store,
        baseline_id,
        baseline_id,
        task,
        cfg,
        max_calls=max_model_calls_per_trial,
        budget=budget,
    )
    candidate_model = bind_probe_model(
        store,
        baseline_id,
        candidate_id,
        task,
        cfg,
        max_calls=max_model_calls_per_trial,
        budget=budget,
    )
    # Git is archived exactly once: even a later working-tree or ref change
    # cannot alter the second trial's archived input.
    if budget is not None:
        budget.checkpoint()
    snapshot = snapshot_git_commit(repo, commit)
    reference = _run_bound_probe(snapshot, cfg, reference_model)
    if reference.status == "error":
        return ReviewedComparison(reference, None, None)
    candidate = _run_bound_probe(snapshot, cfg, candidate_model)
    if candidate.status == "error":
        return ReviewedComparison(reference, candidate, None)

    def limited_judge(request):
        if budget is not None:
            budget.reserve_judge_call()
        return judge(request)

    try:
        verdict = compare(
            task,
            Trajectory(baseline_id, reference.events),
            Trajectory(candidate_id, candidate.events),
            limited_judge,
            sensitive_values=hidden,
        )
    except Exception:  # noqa: BLE001 — untrusted callback details can contain secrets
        raise ProbeUnavailable("comparison judge failed; no judgment accepted") from None
    return ReviewedComparison(reference, candidate, verdict)
