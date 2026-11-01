"""Explicit, bounded in-process parallel probes; no judge, selection or resume.

Only cooperating work using the same budget and, for durable budgets, the
same slot database is counted. The local caller, provider, Git and Docker
daemon/image are trusted. In-flight work is not killed when a peer fails.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from arcen.config import ArcenConfig

from .budget import BudgetExhausted, SharedBudget, TrialConcurrencyFull
from .durable_budget import DurableBudget
from .durable_trial_slots import DurableTrialSlots
from .executor import NativeDockerProbeExecutor
from .manifest import default_manifest
from .probe import ProbeUnavailable
from .probe_execution import ReviewedProbeResult, _reviewed_config
from .probe_hygiene import _reject_snapshot_secrets
from .probe_model import BoundProbeModel, bind_probe_model
from .probe_workspace import snapshot_git_commit
from .resolver import HarnessError
from .store import HarnessStore


@dataclass(frozen=True, slots=True)
class TrialAttempt:
    candidate_id: str
    status: str
    result: ReviewedProbeResult | None = field(repr=False)


@dataclass(frozen=True, slots=True)
class ParallelTrials:
    reference: TrialAttempt
    candidates: tuple[TrialAttempt, ...]
    unstarted: tuple[str, ...]
    stop_reason: str | None
    workspace_sha256: str


def run_reviewed_parallel_trials(
    store: HarnessStore,
    baseline_id: str,
    candidate_ids: tuple[str, ...],
    task: str,
    config: ArcenConfig,
    *,
    repo: str | Path,
    commit: str,
    budget: SharedBudget | DurableBudget,
    workers: int,
    durable_slots: DurableTrialSlots | None = None,
    reviewed_inputs: bool = False,
    max_model_calls_per_trial: int = 4,
    sensitive_values: tuple[str, ...] = (),
    expected_workspace_sha256: str | None = None,
) -> ParallelTrials:
    """Run a reference then bounded waves of independent candidate probes.

    All trials share one archived Git snapshot, reviewed inputs and a shared
    admission budget. Durable budgets additionally require matching persisted
    trial slots, which only limit cooperating users. A failed wave prevents later waves, but its
    other already-started work is awaited, not cancelled. Results are ephemeral
    and unjudged. This does not select, approve, adopt, persist or resume.
    """
    if reviewed_inputs is not True:
        raise HarnessError("explicit review of parallel trial inputs is required")
    if type(store) is not HarnessStore or type(budget) not in (SharedBudget, DurableBudget):
        raise HarnessError("parallel trials require a store and supported shared budget")
    if type(budget) is SharedBudget:
        if durable_slots is not None:
            raise HarnessError("in-process budget cannot use durable trial slots")
    elif (
        type(durable_slots) is not DurableTrialSlots
        or durable_slots.budget.id != budget.id
        or durable_slots.budget.store.root != budget.store.root
        or budget.store.root != store.root
    ):
        raise HarnessError("durable budget requires matching durable trial slots")
    if (
        type(baseline_id) is not str
        or type(candidate_ids) is not tuple
        or not 2 <= len(candidate_ids) <= 5
        or any(type(value) is not str for value in candidate_ids)
        or len(set(candidate_ids)) != len(candidate_ids)
        or baseline_id in candidate_ids
    ):
        raise HarnessError("parallel trials require 2 to 5 distinct candidates")
    if type(workers) is not int or not 1 <= workers <= min(4, len(candidate_ids)):
        raise HarnessError("parallel workers must be between 1 and min(4, candidate count)")
    if durable_slots is not None and workers > durable_slots.snapshot().max_active:
        raise HarnessError("parallel workers exceed durable concurrency limit")
    if expected_workspace_sha256 is not None and (
        type(expected_workspace_sha256) is not str
        or not re.fullmatch(r"[0-9a-f]{64}", expected_workspace_sha256)
    ):
        raise HarnessError("invalid expected workspace hash")
    if (
        type(sensitive_values) is not tuple
        or len(sensitive_values) > 31
        or any(type(value) is not str or not 4 <= len(value) <= 256 for value in sensitive_values)
    ):
        raise HarnessError("invalid sensitive values")
    baseline = store.get_manifest(baseline_id)
    packaged = default_manifest()
    if (
        baseline.schema_version != packaged.schema_version
        or baseline.components != packaged.components
    ):
        raise HarnessError("parallel trials require the unchanged packaged baseline")
    cfg = _reviewed_config(config, True)
    if cfg.sandbox.network != "none" or cfg.sandbox.backend not in ("auto", "docker"):
        raise HarnessError("parallel trials require Docker with networking disabled")
    if len(cfg.provider.api_key) > 256:
        raise HarnessError("provider credential exceeds comparison redaction limit")
    hidden = tuple(
        dict.fromkeys(
            (*sensitive_values, *((cfg.provider.api_key,) if cfg.provider.api_key else ()))
        )
    )
    # Admission preflight is a snapshot, never a reservation or runtime cap.
    budget.require_available(
        trials=1 + len(candidate_ids), model_calls=1 + len(candidate_ids), judge_calls=0
    )
    models = tuple(
        bind_probe_model(
            store,
            baseline_id,
            identifier,
            task,
            cfg,
            max_calls=max_model_calls_per_trial,
            budget=budget,
            sensitive_values=sensitive_values,
        )
        for identifier in (baseline_id, *candidate_ids)
    )
    budget.checkpoint()
    snapshot = snapshot_git_commit(repo, commit)
    if expected_workspace_sha256 is not None and snapshot.sha256 != expected_workspace_sha256:
        raise HarnessError("reviewed workspace snapshot does not match expected hash")
    _reject_snapshot_secrets(snapshot, hidden)
    executor = NativeDockerProbeExecutor()

    def attempt(model: BoundProbeModel) -> TrialAttempt:
        identifier = model.plan.candidate_id
        try:
            if durable_slots is None:
                result = executor.execute(snapshot, cfg, model)
            else:
                with durable_slots.trial_slot():
                    result = executor.execute(snapshot, cfg, model)
        except TrialConcurrencyFull:
            return TrialAttempt(identifier, "concurrency_full", None)
        except BudgetExhausted:
            return TrialAttempt(identifier, "budget_closed", None)
        except ProbeUnavailable:
            budget.stop()  # isolation or cleanup uncertainty: fail conservatively
            return TrialAttempt(identifier, "unavailable", None)
        except Exception:  # noqa: BLE001 — provider and executor details may contain secrets
            budget.stop()
            return TrialAttempt(identifier, "unavailable", None)
        if (
            type(result) is not ReviewedProbeResult
            or result.candidate_id != identifier
            or result.baseline_id != baseline_id
            or result.commit != snapshot.commit
            or result.workspace_sha256 != snapshot.sha256
        ):
            budget.stop()
            return TrialAttempt(identifier, "unavailable", None)
        return TrialAttempt(identifier, "ok" if result.status == "ok" else "failed", result)

    reference = attempt(models[0])
    if reference.status != "ok":
        return ParallelTrials(
            reference, (), candidate_ids, "reference_" + reference.status, snapshot.sha256
        )
    attempts: list[TrialAttempt] = []
    submitted = 0
    stop_reason = None
    try:
        pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="arcen-probe")
    except Exception:  # noqa: BLE001 — no work started; avoid leaking executor errors
        budget.stop()
        return ParallelTrials(
            reference, (), candidate_ids, "scheduler_unavailable", snapshot.sha256
        )
    with pool:
        for offset in range(0, len(candidate_ids), workers):
            try:
                budget.checkpoint()
            except BudgetExhausted:
                stop_reason = "budget_closed"
                break
            futures = []
            for model in models[1 + offset : 1 + offset + workers]:
                try:
                    futures.append(pool.submit(attempt, model))
                    submitted += 1
                except Exception:  # noqa: BLE001 — already submitted work is still awaited
                    budget.stop()
                    stop_reason = "scheduler_unavailable"
                    break
            wave = tuple(future.result() for future in futures)
            attempts.extend(wave)
            if stop_reason is not None:
                break
            if any(item.status != "ok" for item in wave):
                stop_reason = "candidate_wave_failed"
                break
    return ParallelTrials(
        reference, tuple(attempts), candidate_ids[submitted:], stop_reason, snapshot.sha256
    )
