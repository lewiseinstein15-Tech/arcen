"""Interactive manual campaign CLI. Never approves or adopts candidates."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from arcen.config import DEFAULT_CONFIG, ArcenConfig, deep_merge, migrate_legacy_config
from arcen.plugins.redact_secrets import redact_text

from .campaign_journal import CampaignJournal
from .composer import compose_proposals
from .durable_budget import DurableBudget
from .editor import EDITABLE, MAX_PATCH_BYTES, Proposal, apply_exact_diff
from .manifest import Manifest, default_manifest
from .model import content_hash
from .policy import review_candidate
from .probe_execution import _reviewed_config
from .probe_model import bind_probe_model
from .resolver import HarnessError
from .review import ReviewLedger
from .store import HarnessStore


def _read_text(path: str, limit: int) -> str:
    """Read a bounded regular file; reject final-component symlinks and FIFOs."""
    try:
        fd = os.open(
            Path(path).expanduser(),
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        )
        with os.fdopen(fd, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise HarnessError("input must be a regular file")
            data = source.read(limit + 1)
    except OSError:
        raise HarnessError("cannot read input file") from None
    if len(data) > limit:
        raise HarnessError("input file exceeds size limit")
    try:
        return data.decode("utf-8")
    except UnicodeError:
        raise HarnessError("input file must be UTF-8") from None


def _config(path: str) -> ArcenConfig:
    raw_text = _read_text(path, 64 * 1024)
    try:
        raw = yaml.safe_load(raw_text) or {}
        if type(raw) is not dict:
            raise ValueError("config must be a mapping")
        config = ArcenConfig.model_validate(deep_merge(DEFAULT_CONFIG, migrate_legacy_config(raw)))
    except Exception:  # noqa: BLE001 — config validation errors may include secrets
        raise HarnessError("invalid campaign configuration") from None
    return _reviewed_config(config, True)


def _confirm(prompt: str, expected: str) -> None:
    try:
        actual = input(prompt)
    except (EOFError, KeyboardInterrupt):
        raise HarnessError("campaign cancelled") from None
    if actual.strip() != expected:
        raise HarnessError("campaign cancelled")


def pin_baseline(store: HarnessStore, adopted_id: str, pin: str) -> str:
    if type(pin) is not str or not re.fullmatch(r"fixed:[a-z][a-z0-9_-]{0,31}:[^\s]{1,200}", pin):
        raise HarnessError("baseline requires a fixed provider/model pin")
    adopted = store.get_manifest(adopted_id)
    packaged = default_manifest()
    if (
        adopted.schema_version != packaged.schema_version
        or adopted.components != packaged.components
    ):
        raise HarnessError("baseline pinning requires the unchanged packaged baseline")
    return store.put_manifest(Manifest(adopted.schema_version, pin, adopted.components))


def import_patch(store: HarnessStore, baseline_id: str, path: str, patch_file: str) -> str:
    if type(path) is not str or path not in EDITABLE:
        raise HarnessError("component is not editable")
    patch = _read_text(patch_file, MAX_PATCH_BYTES)
    baseline = store.get_manifest(baseline_id)
    original = store.get_blob(baseline.components[path])
    proposal = Proposal(
        "domain", path, patch, content_hash(original), apply_exact_diff(original, path, patch)
    )
    result = compose_proposals(store, baseline_id, (proposal,))
    if result.candidate_id is None:
        raise HarnessError("patch composition failed")
    review_candidate(store, baseline_id, result.candidate_id)
    return result.candidate_id


def create_plan(
    store: HarnessStore, baseline: str, candidates: tuple[str, ...], task_file: str, commit: str
):
    task = _read_text(task_file, 16000)
    return CampaignJournal(store, create=True).plan(baseline, candidates, task, commit)


def run_interactive(
    store: HarnessStore,
    adopted_id: str,
    identifier: str,
    task_file: str,
    config_file: str,
    repo: str,
    budget_id: str,
) -> int:
    """Review all inputs interactively, then run with a human A/B judge."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise HarnessError("campaign run requires an interactive terminal")
    from .cli import _diff_objects, _safe
    from .manual_campaign import run_manual_campaign

    journal = CampaignJournal(store)
    record = journal.get(identifier)
    if record.state != "ready":
        raise HarnessError("campaign is not ready; automatic resume is unavailable")
    baseline = store.get_manifest(record.baseline)
    packaged = default_manifest()
    if (
        baseline.schema_version != packaged.schema_version
        or baseline.components != packaged.components
    ):
        raise HarnessError("interactive campaign requires the unchanged packaged baseline")
    task = _read_text(task_file, 16000)
    if hashlib.sha256(task.encode("utf-8")).hexdigest() != record.task_sha256:
        raise HarnessError("task file does not match the campaign plan")
    config = _config(config_file)
    budget = DurableBudget(store, budget_id)
    budget.checkpoint()
    # Preflight model bindings and all candidate policies without provider calls.
    bind_probe_model(store, record.baseline, record.baseline, task, config, budget=budget)
    for candidate in record.candidates:
        review_candidate(store, record.baseline, candidate)
        bind_probe_model(store, record.baseline, candidate, task, config, budget=budget)
    try:
        endpoint = urlsplit(config.provider.base_url).hostname or "provider default"
    except ValueError:
        raise HarnessError("invalid provider endpoint") from None
    endpoint = redact_text(endpoint)
    if config.provider.api_key:
        endpoint = endpoint.replace(config.provider.api_key, "[REDACTED]")
    usage = budget.snapshot()
    print(f"Campaign {record.id}; commit {record.commit}; budget {budget.id}")
    print(f"Repository: {_safe(str(Path(repo).expanduser().absolute()))}")
    print(
        f"Budget used: trials={usage.trials}; model calls={usage.model_calls}; judge callbacks={usage.judge_calls}"
    )
    print("Budget is not bound to the plan; verify its limits and repository commit separately.")

    def display_config(value: str) -> str:
        value = redact_text(value)
        if config.provider.api_key:
            value = value.replace(config.provider.api_key, "[REDACTED]")
        return _safe(value)

    print(
        f"Provider: {display_config(config.provider.name)}; model: {display_config(config.provider.model)}; endpoint host: {_safe(endpoint)}"
    )
    print("Review the config file and full endpoint separately; only its host is shown.")
    if record.baseline != adopted_id:
        print("WARNING: the test baseline is not the currently adopted baseline.")
    print("Task (sanitized for terminal display):\n" + _safe(task))
    for candidate in record.candidates:
        print(f"\nCandidate {candidate} — sanitized diff:")
        print(_diff_objects(store, record.baseline, candidate), end="")
    print(
        "\nProvider calls may transmit data and cost money. Committed files and tool output may contain secrets."
    )
    print(
        "Admission limits are NOT token or USD caps. Docker is required; there is no host fallback."
    )
    print(
        "The model can run commands in disposable Docker workspaces. Inspect the commit before running."
    )
    print("A/B judgments will be requested interactively. No candidate is selected or adopted.")
    _confirm(f"Type RUN {record.id} to start: ", f"RUN {record.id}")
    reviews = ReviewLedger(store, create=True)

    def human_judge(request: dict) -> str:
        print("\nBlinded evidence (untrusted; may contain sensitive data):")
        print(json.dumps(request, ensure_ascii=True, indent=2))
        try:
            choice = input("Choose A, B, TIE or CANCEL: ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            raise HarnessError("judge cancelled") from None
        if choice not in {"A", "B", "TIE"}:
            raise HarnessError("judge cancelled")
        return json.dumps(
            {
                "winner": "tie" if choice == "TIE" else choice,
                "confidence": 0.5,
                "reason": "manual preference; confidence not assessed",
            }
        )

    result = run_manual_campaign(
        store,
        record.baseline,
        record.candidates,
        task,
        config,
        human_judge,
        repo=repo,
        commit=record.commit,
        reviews=reviews,
        budget=budget,
        reviewed_inputs=True,
        reviewed_judge_inputs=True,
        journal=journal,
        campaign_id=record.id,
    )
    for item in result.completed:
        print(f"Pending review: {item.review.id}  candidate: {item.candidate_id}")
    if result.stop_reason is not None:
        print(
            f"Campaign stopped: {result.stop_reason}. Inspect the journal and any pending reviews."
        )
        return 1
    print(
        "Campaign completed; pending reviews require separate human inspection. No adoption occurred."
    )
    return 0
