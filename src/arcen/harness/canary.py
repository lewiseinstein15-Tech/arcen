"""Manual, fixed, behavioral canaries; not an adoption or security gate.

Every task uses the same reviewed snapshot in a separate Docker container.
The fixed verifiers can detect simple regressions, not adversarial cheating or
all unsafe behavior. Local Python, the store, clock, daemon and image are trusted.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

from arcen.config import ArcenConfig

from .budget import BudgetExhausted
from .durable_budget import DurableBudget
from .manifest import default_manifest
from .policy import review_candidate
from .probe import ProbeUnavailable
from .probe_execution import _CanaryCommands, _reviewed_config, _run_bound_probe
from .probe_model import bind_probe_model
from .probe_workspace import snapshot_git_commit
from .resolver import HarnessError
from .store import HarnessStore


@dataclass(frozen=True, slots=True)
class CanaryCase:
    id: str
    task: str
    output_file: str
    expected: bytes


def _commands(case: CanaryCase) -> _CanaryCommands:
    """Construct checks only from this module's immutable built-in cases."""
    path = "/workspace/" + case.output_file
    script = (
        "import os,stat,sys\n"
        f"p={path!r}; expected={case.expected!r}\n"
        "try:\n"
        " s=os.lstat(p)\n"
        " if not stat.S_ISREG(s.st_mode) or s.st_size != len(expected): sys.exit(1)\n"
        " with open(p,'rb') as f: actual=f.read(len(expected)+1)\n"
        " sys.exit(0 if actual == expected else 1)\n"
        "except OSError: sys.exit(1)\n"
    )
    return _CanaryCommands(
        "rm -f -- " + shlex.quote(path),
        "/usr/local/bin/python3 -I -c " + shlex.quote(script),
    )


CASES = (
    CanaryCase(
        "exact-number",
        "In the workspace, create .arcen-canary-number.txt with exactly the bytes 42 followed by one newline.",
        ".arcen-canary-number.txt",
        b"42\n",
    ),
    CanaryCase(
        "sha256-abc",
        "In the workspace, create .arcen-canary-sha256.txt containing the lowercase SHA-256 hex digest of the three bytes abc, followed by one newline.",
        ".arcen-canary-sha256.txt",
        b"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\n",
    ),
)


@dataclass(frozen=True, slots=True)
class CanaryFinding:
    case_id: str
    reference: str
    candidate: str


@dataclass(frozen=True, slots=True)
class CanaryReport:
    baseline_id: str
    candidate_id: str
    commit: str
    workspace_sha256: str
    outcome: str  # passed | regression | inconclusive
    findings: tuple[CanaryFinding, ...]


def run_manual_canaries(
    store: HarnessStore,
    baseline_id: str,
    candidate_id: str,
    config: ArcenConfig,
    *,
    repo: str | Path,
    commit: str,
    budget: DurableBudget,
    reviewed_inputs: bool = False,
) -> CanaryReport:
    """Run code-defined canaries manually; never authorize or adopt a change."""
    if reviewed_inputs is not True:
        raise HarnessError("explicit review of canary inputs is required")
    if (
        type(store) is not HarnessStore
        or type(budget) is not DurableBudget
        or budget.store is not store
    ):
        raise HarnessError("canaries require a durable budget for the same store")
    baseline = store.get_manifest(baseline_id)
    packaged = default_manifest()
    if (
        baseline.schema_version != packaged.schema_version
        or baseline.components != packaged.components
    ):
        raise HarnessError("canaries require the unchanged packaged baseline")
    review_candidate(store, baseline_id, candidate_id)
    cfg = _reviewed_config(config, True)
    budget.checkpoint()
    models = tuple(
        (
            bind_probe_model(store, baseline_id, baseline_id, case.task, cfg, budget=budget),
            bind_probe_model(store, baseline_id, candidate_id, case.task, cfg, budget=budget),
        )
        for case in CASES
    )
    budget.checkpoint()
    try:
        snapshot = snapshot_git_commit(repo, commit)
    except (OSError, ValueError):
        raise HarnessError("cannot prepare reviewed Git snapshot") from None
    findings: list[CanaryFinding] = []

    def report(outcome: str) -> CanaryReport:
        return CanaryReport(
            baseline_id, candidate_id, snapshot.commit, snapshot.sha256, outcome, tuple(findings)
        )

    for case, (reference_model, candidate_model) in zip(CASES, models, strict=True):
        try:
            reference = _run_bound_probe(snapshot, cfg, reference_model, canary=_commands(case))
        except (ProbeUnavailable, BudgetExhausted):
            findings.append(CanaryFinding(case.id, "inconclusive", "not-run"))
            return report("inconclusive")
        if reference.status == "error" or reference.canary_passed is None:
            findings.append(CanaryFinding(case.id, "inconclusive", "not-run"))
            return report("inconclusive")
        if reference.status != "ok" or reference.canary_passed is not True:
            findings.append(CanaryFinding(case.id, "failed", "not-run"))
            return report("inconclusive")
        try:
            candidate = _run_bound_probe(snapshot, cfg, candidate_model, canary=_commands(case))
        except (ProbeUnavailable, BudgetExhausted):
            findings.append(CanaryFinding(case.id, "passed", "inconclusive"))
            return report("inconclusive")
        if candidate.status == "error" or candidate.canary_passed is None:
            findings.append(CanaryFinding(case.id, "passed", "inconclusive"))
            return report("inconclusive")
        if candidate.status != "ok" or candidate.canary_passed is not True:
            findings.append(CanaryFinding(case.id, "passed", "failed"))
            return report("regression")
        findings.append(CanaryFinding(case.id, "passed", "passed"))
    return report("passed")
