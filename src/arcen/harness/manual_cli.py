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
from arcen.guardrails.policy import _UniqueSafeLoader
from arcen.plugins.redact_secrets import redact_text

from .campaign_journal import CampaignJournal
from .composer import compose_proposals
from .durable_budget import DurableBudget
from .editor import EDITABLE, MAX_PATCH_BYTES, Proposal, apply_exact_diff
from .manifest import Manifest, default_manifest
from .model import content_hash
from .policy import review_candidate
from .probe_execution import _reviewed_config
from .probe_model import ProbeModelError, _review_input, bind_probe_model
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


def _task_input(store: HarnessStore, task_file: str | None, task_id: str | None) -> str:
    if (task_file is None) == (task_id is None):
        raise HarnessError("choose exactly one task file or task ID")
    if task_file is not None:
        return _read_text(task_file, 16000)
    from .task_bank import TaskBank

    return TaskBank(store).read(task_id)


def _config(path: str) -> ArcenConfig:
    raw_text = _read_text(path, 64 * 1024)
    try:
        # Prevent ambiguous duplicate keys, YAML merge/alias expansion and
        # explicit object tags in operator-reviewed config. This stricter
        # parser is scoped to manual harness commands, not normal ARCEN boot.
        if any(
            isinstance(token, (yaml.AliasToken, yaml.AnchorToken, yaml.TagToken))
            for token in yaml.scan(raw_text)
        ):
            raise ValueError("ambiguous YAML")
        raw = yaml.load(raw_text, Loader=_UniqueSafeLoader) or {}
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
    store: HarnessStore,
    baseline: str,
    candidates: tuple[str, ...],
    task_file: str | None,
    commit: str,
    budget_id: str,
    *,
    task_id: str | None = None,
):
    task = _task_input(store, task_file, task_id)
    budget = DurableBudget(store, budget_id)
    return CampaignJournal(store, create=True).plan(
        baseline, candidates, task, commit, budget=budget
    )


def run_interactive(
    store: HarnessStore,
    adopted_id: str,
    identifier: str,
    task_file: str | None,
    config_file: str,
    repo: str,
    budget_id: str,
    *,
    task_id: str | None = None,
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
    if record.budget_id is None:
        raise HarnessError("legacy unbound campaign; create a new plan with a durable budget")
    if record.budget_id != budget_id:
        raise HarnessError("campaign budget does not match the plan")
    baseline = store.get_manifest(record.baseline)
    packaged = default_manifest()
    if (
        baseline.schema_version != packaged.schema_version
        or baseline.components != packaged.components
    ):
        raise HarnessError("interactive campaign requires the unchanged packaged baseline")
    task = _task_input(store, task_file, task_id)
    if hashlib.sha256(task.encode("utf-8")).hexdigest() != record.task_sha256:
        raise HarnessError("task does not match the campaign plan")
    config = _config(config_file)
    budget = DurableBudget(store, budget_id)
    budget.checkpoint()
    # Preflight model bindings and all candidate policies without provider calls.
    try:
        bind_probe_model(store, record.baseline, record.baseline, task, config, budget=budget)
        for candidate in record.candidates:
            review_candidate(store, record.baseline, candidate)
            bind_probe_model(store, record.baseline, candidate, task, config, budget=budget)
    except ProbeModelError:
        raise HarnessError("model preflight rejected sensitive or invalid input") from None
    try:
        endpoint = urlsplit(config.provider.base_url).hostname or "provider default"
    except ValueError:
        raise HarnessError("invalid provider endpoint") from None
    endpoint = redact_text(endpoint)
    if config.provider.api_key:
        endpoint = endpoint.replace(config.provider.api_key, "[REDACTED]")
    usage = budget.snapshot()
    if usage.stopped:
        raise HarnessError("durable budget closed")
    print(f"Campaign {record.id}; commit {record.commit}; budget {budget.id}")
    print(f"Repository: {_safe(str(Path(repo).expanduser().absolute()))}")
    print(
        f"Budget admissions used/limit: trials={usage.trials}/{usage.max_trials}; "
        f"model calls={usage.model_calls}/{usage.max_model_calls}; "
        f"judge callbacks={usage.judge_calls}/{usage.max_judge_calls}"
    )
    print(
        f"Time until admission cutoff: {usage.admission_seconds_remaining:.1f}s (not a runtime limit)."
    )
    print("The plan is bound to this budget ID; verify the repository commit separately.")

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


def _editor_candidates_interactive(
    store: HarnessStore,
    baseline_id: str,
    task_file: str | None,
    config_file: str,
    budget_id: str,
    k: int,
    *,
    task_id: str | None = None,
) -> tuple[tuple[str, Proposal], ...]:
    """Generate and retain exact, unadopted independent proposals for this process."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise HarnessError("editor requires an interactive terminal")
    if type(k) is not int or not 1 <= k <= 4:
        raise HarnessError("editor k must be between 1 and 4")
    from .cli import _diff_objects, _safe
    from .editor import propose

    baseline = store.get_manifest(baseline_id)
    packaged = default_manifest()
    if (
        baseline.schema_version != packaged.schema_version
        or baseline.components != packaged.components
    ):
        raise HarnessError("editor requires the unchanged packaged baseline")
    task = _task_input(store, task_file, task_id)
    config = _config(config_file)
    budget = DurableBudget(store, budget_id)
    budget.checkpoint()
    try:
        model = bind_probe_model(
            store, baseline_id, baseline_id, task, config, max_calls=2 * k, budget=budget
        )
    except ProbeModelError:
        raise HarnessError("model preflight rejected sensitive or invalid input") from None
    # The editor sends the full component files, not just resolved prompt
    # sections. Screen each before confirmation and before any request.
    try:
        for path in EDITABLE:
            _review_input(
                store.get_blob(baseline.components[path]).decode("utf-8"), config.provider.api_key
            )
    except Exception:  # noqa: BLE001 — never disclose detected secrets
        raise HarnessError("editor input contains invalid or sensitive component data") from None
    usage = budget.snapshot()
    if usage.stopped or usage.max_model_calls - usage.model_calls < 2 * k:
        raise HarnessError("editor requires sufficient open model-call admissions")
    try:
        endpoint = urlsplit(config.provider.base_url).hostname or "provider default"
    except ValueError:
        raise HarnessError("invalid provider endpoint") from None

    def display(value: str) -> str:
        value = redact_text(value)
        if config.provider.api_key:
            value = value.replace(config.provider.api_key, "[REDACTED]")
        return _safe(value)

    print(f"Editor baseline: {baseline_id}; budget: {budget.id}; proposals: {2 * k}")
    print(
        f"Provider: {display(config.provider.name)}; model: {display(config.provider.model)}; endpoint host: {display(endpoint)}"
    )
    print(
        f"Budget model admissions: {usage.model_calls}/{usage.max_model_calls}; needed: {2 * k}; cutoff in {usage.admission_seconds_remaining:.1f}s"
    )
    print("Task (sanitized):\n" + _safe(task))
    print("This sends the task and all five editable packaged components to the provider.")
    print("Review the exact task, baseline components, full endpoint and config separately.")
    print(
        "Provider calls may transmit sensitive data and cost money; no USD/token cap is enforced."
    )
    print("Generated diffs are untrusted, untested and unapproved. Nothing is executed or adopted.")
    _confirm(f"Type EDIT {baseline_id} to start: ", f"EDIT {baseline_id}")

    def request_editor(request: dict) -> str:
        message = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
        return model.complete("planner", [{"role": "user", "content": message}]).text

    try:
        proposals = propose(store, baseline_id, task, (request_editor,), k=k)
    except Exception:  # noqa: BLE001 — untrusted provider/model details may contain secrets
        raise HarnessError(
            "editor generation failed; inspect budget usage before retrying"
        ) from None
    generated = []
    for proposal in proposals:
        result = compose_proposals(store, baseline_id, (proposal,))
        if result.candidate_id is None:
            raise HarnessError("editor candidate composition failed")
        review_candidate(store, baseline_id, result.candidate_id)
        generated.append((result.candidate_id, proposal))
        print(f"\nUnadopted {proposal.scope} candidate: {result.candidate_id}")
        print(_diff_objects(store, baseline_id, result.candidate_id), end="")
    print("\nCandidates are untrusted; inspect them before planning trials. No refs moved.")
    return tuple(generated)


def editor_interactive(
    store: HarnessStore,
    baseline_id: str,
    task_file: str | None,
    config_file: str,
    budget_id: str,
    k: int,
    *,
    task_id: str | None = None,
) -> int:
    _editor_candidates_interactive(
        store, baseline_id, task_file, config_file, budget_id, k, task_id=task_id
    )
    return 0


def guided_workflow(
    store: HarnessStore,
    baseline_id: str,
    task_id: str,
    config_file: str,
    repo: str,
    commit: str,
    budget_id: str,
    k: int,
) -> int:
    """Run an explicitly gated editor-to-manual-comparison flow; never adopt."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise HarnessError("guided workflow requires an interactive terminal")
    if type(k) is not int or not 1 <= k <= 4:
        raise HarnessError("editor k must be between 1 and 4")
    if type(commit) is not str or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", commit):
        raise HarnessError("commit must be a full lowercase Git object ID")
    if not Path(repo).expanduser().is_dir():
        raise HarnessError("repository directory is missing")
    # A stored ID is used throughout, so rereads verify the exact same task
    # bytes rather than silently rereading a mutable file between stages.
    _task_input(store, None, task_id)
    budget = DurableBudget(store, budget_id)
    budget.checkpoint()
    usage = budget.snapshot()
    if (
        usage.stopped
        or usage.max_trials - usage.trials < 2
        or usage.max_judge_calls - usage.judge_calls < 1
        or usage.max_model_calls - usage.model_calls < 2 * k + 2
    ):
        raise HarnessError(
            "workflow requires at least two trial admissions, one judge admission and editor plus two model admissions"
        )
    # Preflight an actual bounded, sanitized Git snapshot before spending on
    # editor requests. The campaign takes a fresh snapshot after confirmation;
    # this local preview hash is not authenticated or transactionally bound.
    from arcen.sandbox.workspace import WorkspaceError

    from .cli import _safe
    from .probe_workspace import snapshot_git_commit

    try:
        preview_sha = snapshot_git_commit(repo, commit).sha256
    except WorkspaceError:
        raise HarnessError("repository/commit preflight failed; inspect the Git snapshot") from None
    print(
        "Guided manual workflow: editor → select or compose → plan → confirmed comparison → pending review."
    )
    print(f"Repository: {_safe(str(Path(repo).expanduser().absolute()))}; commit: {commit}")
    print(f"Task ID: {task_id}; preliminary workspace SHA-256: {preview_sha}")
    print(
        "No automatic selection, approval, adoption or resume. Generated objects may persist if cancelled."
    )
    print("The budget minimum is not a reservation or a guarantee the comparison will finish.")
    print(
        "The campaign re-snapshots after confirmation; this preview is not an authenticated binding."
    )
    print("Review the commit and provider data exposure separately before each confirmation.")
    candidates = _editor_candidates_interactive(
        store, baseline_id, None, config_file, budget_id, k, task_id=task_id
    )
    # Each proposal is retained in memory only and must independently apply to
    # the same baseline. Never reconstruct proposal patches from terminal text.
    unique: dict[str, Proposal] = {}
    for identifier, proposal in candidates:
        unique.setdefault(identifier, proposal)
    if not unique:
        raise HarnessError("editor produced no candidates")
    print(
        "\nChoose or compose generated candidates for a manual comparison; this does not approve them:"
    )
    for identifier in unique:
        print(f"  {identifier}")
    print(
        "COMPOSE merges exact proposals syntactically; conflicting or touching edits are refused."
    )
    print(
        "Inputs have not been compared; a conflict-free merge does not prove safety or improvement."
    )
    try:
        selection = input("Type SELECT ID, COMPOSE ID ID [ID ...], or CANCEL: ").strip()
    except (EOFError, KeyboardInterrupt):
        raise HarnessError(
            "workflow cancelled after editor; generated objects may remain"
        ) from None
    if len(selection) > 1024:
        raise HarnessError("workflow cancelled after editor; generated objects may remain")
    words = selection.split()
    if len(words) == 2 and words[0] == "SELECT" and words[1] in unique:
        candidate = words[1]
    elif (
        3 <= len(words) <= 9
        and words[0] == "COMPOSE"
        and len(set(words[1:])) == len(words) - 1
        and all(identifier in unique for identifier in words[1:])
    ):
        budget.checkpoint()
        identifiers = tuple(words[1:])
        # Verify stored inputs again before composing; candidate IDs and local
        # proposal objects are not authenticated evidence or approvals.
        for identifier in identifiers:
            review_candidate(store, baseline_id, identifier)
        composition = compose_proposals(store, baseline_id, tuple(unique[x] for x in identifiers))
        if composition.conflicts:
            for conflict in composition.conflicts:
                print(
                    f"Conflict: {conflict.path} between {identifiers[conflict.first]} and {identifiers[conflict.second]}"
                )
            raise HarnessError("composition conflicts; no composite candidate or plan created")
        if composition.candidate_id is None:
            raise HarnessError("composition did not produce a candidate")
        candidate = composition.candidate_id
        review_candidate(store, baseline_id, candidate)
        from .cli import _diff_objects

        print(f"\nUnadopted composite candidate: {candidate}")
        print("Composite diff (sanitized; untrusted and untested):")
        print(_diff_objects(store, baseline_id, candidate), end="")
        print("Composition can persist even if cancelled. It is not approval or adoption.")
        _confirm(f"Type USE {candidate} to plan its comparison: ", f"USE {candidate}")
    else:
        raise HarnessError("workflow cancelled after editor; generated objects may remain")
    record = create_plan(store, baseline_id, (candidate,), None, commit, budget_id, task_id=task_id)
    print(f"Created campaign plan: {record.id}; state={record.state}; budget={budget_id}")
    print(
        "If the next step is cancelled or fails, inspect campaign status and budget; do not auto-resume."
    )
    from .lineage import HarnessLineage

    adopted = HarnessLineage(store, read_only=True).resolve("refs/heads/adopted")
    result = run_interactive(
        store, adopted, record.id, None, config_file, repo, budget_id, task_id=task_id
    )
    if result == 0:
        print(
            "Inspect the pending review with 'arcen harness --store STORE review show REVIEW_ID'; decisions never adopt."
        )
    return result


def canary_interactive(
    store: HarnessStore,
    baseline_id: str,
    candidate_id: str,
    config_file: str,
    repo: str,
    commit: str,
    budget_id: str,
) -> int:
    """Explicitly review and run fixed canaries; never authorize adoption."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise HarnessError("canary run requires an interactive terminal")
    from .canary import CASES, run_manual_canaries
    from .cli import _diff_objects, _safe

    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", commit):
        raise HarnessError("commit must be a full lowercase Git object ID")
    baseline = store.get_manifest(baseline_id)
    packaged = default_manifest()
    if (
        baseline.schema_version != packaged.schema_version
        or baseline.components != packaged.components
    ):
        raise HarnessError("canaries require the unchanged packaged baseline")
    review_candidate(store, baseline_id, candidate_id)
    config = _config(config_file)
    budget = DurableBudget(store, budget_id)
    budget.checkpoint()
    try:
        for case in CASES:
            bind_probe_model(store, baseline_id, baseline_id, case.task, config, budget=budget)
            bind_probe_model(store, baseline_id, candidate_id, case.task, config, budget=budget)
    except ProbeModelError:
        raise HarnessError("canary preflight rejected sensitive or invalid input") from None
    usage = budget.snapshot()
    if usage.stopped:
        raise HarnessError("durable budget closed")
    try:
        endpoint = urlsplit(config.provider.base_url).hostname or "provider default"
    except ValueError:
        raise HarnessError("invalid provider endpoint") from None

    def display(value: str) -> str:
        value = redact_text(value)
        if config.provider.api_key:
            value = value.replace(config.provider.api_key, "[REDACTED]")
        return _safe(value)

    print("Manual behavioral canaries")
    print(f"Baseline:  {baseline_id}")
    print(f"Candidate: {candidate_id}")
    print(f"Repository: {_safe(str(Path(repo).expanduser().absolute()))}; commit: {commit}")
    print(
        f"Provider: {display(config.provider.name)}; model: {display(config.provider.model)}; host: {display(endpoint)}"
    )
    print(
        f"Budget: {budget.id}; trials {usage.trials}/{usage.max_trials}; model calls {usage.model_calls}/{usage.max_model_calls}; cutoff in {usage.admission_seconds_remaining:.1f}s"
    )
    print(
        f"Up to {2 * len(CASES)} trials and {8 * len(CASES)} model-call admissions; may stop earlier."
    )
    print("Candidate sanitized diff:\n" + _diff_objects(store, baseline_id, candidate_id), end="")
    print("\nPublic fixed tasks and expected output:")
    for case in CASES:
        print(f"- {case.id}: {_safe(case.task)}")
        print(f"  Expected bytes: {case.expected!r}")
    print(
        "Review the commit, config and full endpoint separately. Provider calls may expose data and cost money."
    )
    print(
        "Docker required, no host fallback. Admission limits are not USD/token caps or runtime cancellation."
    )
    print(
        "These simple public tests are gameable and are NOT a security proof, approval or adoption gate."
    )
    _confirm(f"Type CANARY {candidate_id} to start: ", f"CANARY {candidate_id}")
    report = run_manual_canaries(
        store,
        baseline_id,
        candidate_id,
        config,
        repo=repo,
        commit=commit,
        budget=budget,
        reviewed_inputs=True,
    )
    for item in report.findings:
        print(f"{item.case_id}: baseline={item.reference}; candidate={item.candidate}")
    print(f"Canary result: {report.outcome}; workspace sha256: {report.workspace_sha256}")
    print("Result is unsigned and is not an adoption authorization. No refs moved.")
    return 0 if report.outcome == "passed" else 1
