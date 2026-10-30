"""Explicit reviewed, bounded candidate trial; not the campaign probe API.

This experimental Python-only path runs a candidate on a reviewed Git commit in
one Docker container, without adoption, spawn, session persistence or fallback.
Inputs may still contain secrets that pattern-based filtering cannot detect.
"""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from arcen.agents.draft import (
    DIRECT_NO_PROVIDER_ANSWER,
    NO_PLAN_ANSWER,
    NO_PROVIDER_ANSWER,
    DraftPlanner,
)
from arcen.agents.forge import ForgeExecutor
from arcen.agents.temper import TemperVerifier
from arcen.config import ArcenConfig, resolve_secrets
from arcen.llm.client import ProviderError
from arcen.stream.events import Answer, RunDone, RunError, RunStart, to_dict

from .budget import BudgetExhausted, SharedBudget
from .durable_budget import DurableBudget
from .probe import ProbeUnavailable
from .probe_container import open_probe_container, redact_probe_value
from .probe_model import BoundProbeModel, bind_probe_model
from .probe_workspace import GitSnapshot, snapshot_git_commit
from .resolver import HarnessError
from .store import HarnessStore

_MAX_STEPS = 4
_MAX_COMMAND_BYTES = 8192
_MAX_COMMAND_SECONDS = 30
_REFUSALS = {DIRECT_NO_PROVIDER_ANSWER, NO_PLAN_ANSWER, NO_PROVIDER_ANSWER}


@dataclass(frozen=True, slots=True)
class ReviewedProbeResult:
    baseline_id: str
    candidate_id: str
    commit: str
    workspace_sha256: str
    status: str
    events: tuple[dict, ...] = field(repr=False)
    canary_passed: bool | None = None


@dataclass(frozen=True, slots=True)
class _CanaryCommands:
    """Trusted, code-defined commands; not a public verifier authority."""

    prepare: str
    verify: str


class _Collector:
    def __init__(self, secrets: tuple[str, ...]):
        self.events: list[dict] = []
        self.secrets = secrets

    def emit(self, event) -> None:
        wire = to_dict(event)
        wire["seq"] = len(self.events) + 1
        wire["ts"] = time.time()
        clean = redact_probe_value(wire, self.secrets)
        if type(clean) is not dict or not {"seq", "type", "ts"} <= set(clean):
            raise ProbeUnavailable("probe event could not be safely recorded")
        self.events.append(clean)


class _BoundedGateway:
    """Keep all dispatches inside the redacting Docker gateway and time cap."""

    supports_host_diff = False

    def __init__(self, inner, budget: SharedBudget | DurableBudget | None = None):
        self._inner = inner
        self._budget = budget

    def dispatch(self, name: str, args: dict) -> dict:
        if name != "bash" or type(args) is not dict:
            return {"ok": False, "result": None, "error": "unsupported probe tool"}
        if set(args) - {"cmd", "cwd", "timeout_s"} or type(args.get("cmd")) is not str:
            return {"ok": False, "result": None, "error": "invalid probe command"}
        cmd = args["cmd"]
        try:
            size = len(cmd.encode("utf-8"))
        except UnicodeError:
            return {"ok": False, "result": None, "error": "invalid probe command"}
        if not cmd.strip() or size > _MAX_COMMAND_BYTES:
            return {"ok": False, "result": None, "error": "invalid probe command"}
        cwd = args.get("cwd")
        if cwd not in (None, ".", "/workspace"):
            return {"ok": False, "result": None, "error": "probe cwd must be workspace root"}
        timeout = args.get("timeout_s", _MAX_COMMAND_SECONDS)
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout < 0.1:
            return {"ok": False, "result": None, "error": "invalid probe timeout"}
        bounded = {"cmd": cmd, "timeout_s": min(timeout, _MAX_COMMAND_SECONDS)}
        if self._budget is not None:
            try:
                self._budget.checkpoint()
            except BudgetExhausted:
                return {"ok": False, "result": None, "error": "shared probe budget closed"}
        return self._inner.dispatch("bash", bounded)


def _reviewed_config(config: ArcenConfig, reviewed_inputs: bool) -> ArcenConfig:
    """Validate and freeze provider secrets and endpoint once for a trial."""
    if reviewed_inputs is not True:
        raise HarnessError("explicit review of workspace, prompts and task is required")
    if type(config) is not ArcenConfig:
        raise HarnessError("invalid probe configuration")
    try:
        cfg = ArcenConfig.model_validate(config.model_dump())
    except ValidationError:
        raise HarnessError("invalid probe configuration") from None
    resolved, missing = resolve_secrets(
        {"api_key": cfg.provider.api_key, "base_url": cfg.provider.base_url}
    )
    if missing:
        raise HarnessError("probe provider configuration has unresolved environment references")
    cfg.provider.api_key = str(resolved.get("api_key") or "").strip()
    cfg.provider.base_url = str(resolved.get("base_url") or "").strip()
    return cfg


def run_reviewed_probe(
    store: HarnessStore,
    baseline_id: str,
    candidate_id: str,
    task: str,
    config: ArcenConfig,
    *,
    repo: str | Path,
    commit: str,
    reviewed_inputs: bool = False,
    max_model_calls: int = 4,
    budget: SharedBudget | DurableBudget | None = None,
) -> ReviewedProbeResult:
    """Run one explicitly reviewed trial in a disposable Docker workspace.

    The caller attests they reviewed the commit, prompts and task for provider
    exposure. This does not prove the data secret-free. No adoption is performed.
    """
    cfg = _reviewed_config(config, reviewed_inputs)
    model = bind_probe_model(
        store, baseline_id, candidate_id, task, cfg, max_calls=max_model_calls, budget=budget
    )
    if budget is not None:
        budget.checkpoint()
    snapshot = snapshot_git_commit(repo, commit)
    return _run_bound_probe(snapshot, cfg, model)


def _run_bound_probe(
    snapshot: GitSnapshot,
    cfg: ArcenConfig,
    model: BoundProbeModel,
    *,
    canary: _CanaryCommands | None = None,
) -> ReviewedProbeResult:
    """Run already-validated model and snapshot; never accept either from a CLI."""
    if model.budget is not None:
        model.budget.reserve_trial()
    baseline_id, candidate_id, task = (
        model.plan.baseline_id,
        model.plan.candidate_id,
        model.plan.task,
    )
    secrets = (cfg.provider.api_key,) if cfg.provider.api_key else ()
    collector = _Collector(secrets)
    start = time.monotonic()
    status = "error"
    executed = 0
    canary_passed = None
    try:
        with open_probe_container(snapshot, cfg) as inner:
            gateway = _BoundedGateway(inner, model.budget)
            if canary is not None:
                prepared = gateway.dispatch("bash", {"cmd": canary.prepare, "timeout_s": 10})
                if prepared.get("ok") is not True:
                    raise ProbeUnavailable("canary preparation failed")
            collector.emit(
                RunStart(
                    seq=0,
                    run_id=f"probe-{uuid.uuid4().hex[:12]}",
                    goal=task,
                    harness_ref=f"sha256:{candidate_id}",
                )
            )
            try:
                draft = DraftPlanner(llm=model, emit=collector.emit, max_steps=_MAX_STEPS)
                initial = draft.open_turn(task)
                final = initial[-1] if initial else None
                if final is None:
                    status = "failed"
                elif final.TYPE == "answer":
                    status = "failed" if final.text in _REFUSALS else "ok"
                elif final.TYPE != "plan" or not final.steps:
                    status = "failed"
                elif any(step.get("tool") != "bash" for step in final.steps):
                    collector.emit(
                        Answer(seq=0, text="Probe failed: plan requested an unsupported tool.")
                    )
                    status = "failed"
                else:
                    forge = ForgeExecutor(gateway, emit=collector.emit)
                    last_cmd = None
                    status = "ok"
                    for step in final.steps:
                        if type(step.get("args")) is not dict:
                            status = "failed"
                            break
                        events = forge.execute_step(step)
                        executed += 1
                        if not events[1].ok:
                            status = "failed"
                            break
                        last_cmd = step["args"]["cmd"]
                    if status == "ok" and last_cmd is not None:
                        temper = TemperVerifier(gateway, emit=collector.emit, reruns=0)
                        verdict = temper.verify(
                            step=executed, target="reviewed probe", checks=[last_cmd]
                        )
                        status = "ok" if verdict[-1].TYPE == "step.pass" else "failed"
                    collector.emit(
                        Answer(
                            seq=0, text="Probe completed." if status == "ok" else "Probe failed."
                        )
                    )
            except ProviderError:
                status = "error"
            except Exception:  # noqa: BLE001 — do not expose untrusted inputs/errors
                status = "error"
            if canary is not None and status in {"ok", "failed"}:
                checked = gateway.dispatch("bash", {"cmd": canary.verify, "timeout_s": 10})
                result = checked.get("result")
                if (
                    type(result) is not dict
                    or type(result.get("exit")) is not int
                    or result["exit"] not in (0, 1)
                    or type(checked.get("ok")) is not bool
                    or checked["ok"] != (result["exit"] == 0)
                ):
                    raise ProbeUnavailable("canary verification failed")
                canary_passed = result["exit"] == 0
        # Emit the terminal event only after strict container teardown succeeded.
        if status == "error":
            collector.emit(
                RunError(seq=0, code="PROBE_FAILED", message="Probe failed; no result accepted.")
            )
        else:
            collector.emit(
                RunDone(
                    seq=0,
                    status=status,
                    steps=executed,
                    duration_s=round(time.monotonic() - start, 4),
                )
            )
    except Exception:  # noqa: BLE001 — never report success when isolation/cleanup fails
        raise ProbeUnavailable(
            "reviewed probe isolation or cleanup failed; no result accepted"
        ) from None
    return ReviewedProbeResult(
        baseline_id,
        candidate_id,
        snapshot.commit,
        snapshot.sha256,
        status,
        tuple(collector.events),
        canary_passed,
    )
