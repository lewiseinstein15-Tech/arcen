"""Fail-closed probe preflight; candidate execution is not implemented.

Preparation only reads verified store objects and resolves prompts. It does
not execute a task, create a container, clone a workspace, contact a provider,
or grant approval. The active runtime must never silently use a candidate until
an independently verified, credential-safe Docker probe implementation exists.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from arcen.config import ArcenConfig

from .editor import EDITABLE
from .manifest import check_model_pin, default_manifest
from .resolver import HarnessError, HarnessResolver, ResolvedPrompts
from .store import HarnessStore


class ProbeUnavailable(HarnessError):
    """Probe execution is not ready; there is no host fallback."""


@dataclass(frozen=True, slots=True)
class ProbePlan:
    """Validated immutable inputs, not a capability to run or adopt a harness."""

    baseline_id: str
    candidate_id: str
    model_pin: str
    changed_paths: tuple[str, ...]
    task: str = field(repr=False)
    prompts: ResolvedPrompts = field(repr=False)


def prepare_probe(
    store: HarnessStore,
    baseline_id: str,
    candidate_id: str,
    task: str,
    config: ArcenConfig,
) -> ProbePlan:
    """Validate common baseline/candidate constraints without executing either.

    The model must be explicitly pinned; Tier-0 policy and registry metadata
    must match the currently packaged baseline. Only editor-allowed prompt files
    may differ. This is defense in depth, not a human approval or proof of safety.
    """
    if type(task) is not str or not task.strip() or len(task) > 4000:
        raise HarnessError("invalid probe task")
    base = store.get_manifest(baseline_id)
    candidate = store.get_manifest(candidate_id)
    packaged = default_manifest()
    if base.model_pin == "provider-configured" or not base.model_pin.startswith("fixed:"):
        raise HarnessError("probe requires an explicit fixed model pin")
    if candidate.model_pin != base.model_pin:
        raise HarnessError("candidate cannot change the probe model pin")
    check_model_pin(base, config)
    for path in ("guardrails/policy.yaml", "tools/registry.toml"):
        if base.components[path] != packaged.components[path]:
            raise HarnessError(f"baseline changes protected component: {path}")
        if candidate.components[path] != packaged.components[path]:
            raise HarnessError(f"candidate changes protected component: {path}")
    changed = tuple(
        sorted(
            path for path in base.components if base.components[path] != candidate.components[path]
        )
    )
    if any(path not in EDITABLE for path in changed):
        raise HarnessError("candidate changes a protected component")
    # This resolves only in a temporary directory with fixed allowlisted names.
    # No source, plugin, policy, or arbitrary path is ever materialized.
    with tempfile.TemporaryDirectory(prefix="arcen-probe-preflight-") as directory:
        root = Path(directory)
        for path in EDITABLE:
            dest = root / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(store.get_blob(candidate.components[path]))
        prompts = HarnessResolver(root).resolve()
    return ProbePlan(baseline_id, candidate_id, base.model_pin, changed, task, prompts)


def run_probe(plan: ProbePlan) -> None:
    """Always refuse until quarantine and credential isolation are implemented."""
    raise ProbeUnavailable(
        "Probe execution is not available: isolated workspace, credential envelope, "
        "mandatory redaction and selected-harness execution are not implemented."
    )
