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
    workspace_sha256: str | None = None,
):
    task = _task_input(store, task_file, task_id)
    budget = DurableBudget(store, budget_id)
    return CampaignJournal(store, create=True).plan(
        baseline, candidates, task, commit, budget=budget, workspace_sha256=workspace_sha256
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
    expected_workspace_sha256: str | None = None,
) -> int:
    """Review all inputs interactively, then run with a human A/B judge."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise HarnessError("campaign run requires an interactive terminal")
    if expected_workspace_sha256 is not None and (
        type(expected_workspace_sha256) is not str
        or not re.fullmatch(r"[0-9a-f]{64}", expected_workspace_sha256)
    ):
        raise HarnessError("invalid expected workspace hash")
    from .cli import _diff_objects, _safe
    from .manual_campaign import run_manual_campaign

    journal = CampaignJournal(store)
    record = journal.get(identifier)
    if record.workspace_sha256 is not None:
        if (
            expected_workspace_sha256 is not None
            and expected_workspace_sha256 != record.workspace_sha256
        ):
            raise HarnessError("campaign workspace does not match the plan")
        expected_workspace_sha256 = record.workspace_sha256
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
    if expected_workspace_sha256 is not None:
        print(f"Required workspace SHA-256: {expected_workspace_sha256}")
        print("This local hash is unsigned and is not an authenticity or safety proof.")
        if record.workspace_sha256 is None:
            print("This hash is invocation-only and is not persisted in the plan.")
        else:
            print("This hash is bound to the plan; interrupted runs are not automatically resumed.")

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
    print(
        "A/B judgments will be requested interactively. No winner is selected for adoption, and no candidate is adopted."
    )
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

    def show_progress(event: dict) -> None:
        # All values are validated, code-defined progress metadata. This is
        # informational, not an authenticated event log or an approval.
        kind = event["type"]
        if kind == "harness.campaign.start":
            message = f"Starting manual campaign with {event['candidate_count']} candidate(s)."
        elif kind == "harness.policy":
            message = f"Static review passed: {event['candidate_id']} (not adoption approval)."
        elif kind == "harness.probe.start":
            message = f"Starting {event['role']} probe: {event['candidate_id']}"
        elif kind == "harness.probe.done":
            message = f"Finished {event['role']} probe: {event['status']}"
        elif kind == "harness.judge":
            message = (
                f"Manual comparison: {event['winner']} (confidence {event['confidence']:.2f})."
            )
        elif kind == "harness.review":
            message = f"Review pending: {event['review_id']}"
        else:
            message = f"Campaign {event['status']}; pending reviews: {event['completed']}."
        print(f"[harness] {message}", flush=True)

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
        on_progress=show_progress,
        expected_workspace_sha256=expected_workspace_sha256,
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
    experience_topics: tuple[str, ...] = (),
) -> tuple[tuple[str, Proposal], ...]:
    """Generate and retain exact, unadopted independent proposals for this process."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise HarnessError("editor requires an interactive terminal")
    if type(k) is not int or not 1 <= k <= 4:
        raise HarnessError("editor k must be between 1 and 4")
    from .cli import _diff_objects, _safe
    from .editor import propose

    if type(experience_topics) is not tuple or len(experience_topics) > 3:
        raise HarnessError("select at most three distinct experience topics")
    if experience_topics:
        from .experience import _validate_topic

        for topic in experience_topics:
            _validate_topic(topic)
        if len(set(experience_topics)) != len(experience_topics):
            raise HarnessError("select at most three distinct experience topics")

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

    def selected_experience():
        # Lock is held only while reading, never while waiting for the operator.
        from .experience_cli_store import open_cli_experience

        ledger = ReviewLedger(store)
        with open_cli_experience(store, ledger) as library:
            by_topic = {lesson.topic: lesson for lesson in library.active()}
            selected = []
            for topic in experience_topics:
                lesson = by_topic.get(topic)
                if lesson is None:
                    raise HarnessError("selected experience is missing or expired")
                if lesson.baseline_id != baseline_id:
                    raise HarnessError(
                        "selected experience baseline does not match editor baseline"
                    )
                # Score decays with wall time; identity and content must stay fixed.
                selected.append(
                    (
                        lesson.fact_id,
                        lesson.topic,
                        lesson.text,
                        lesson.review_id,
                        lesson.baseline_id,
                        lesson.candidate_id,
                        lesson.created_at,
                        lesson.expires_at,
                    )
                )
            return tuple(selected)

    selected = selected_experience() if experience_topics else ()
    try:
        for item in selected:
            _review_input(item[2], config.provider.api_key)
    except ProbeModelError:
        raise HarnessError("selected experience contains sensitive or invalid data") from None
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
    if selected:
        print("Selected notes will be sent to the provider as untrusted data, not policy.")
        print("They may contain prompt injection, sensitive data or mistakes; review every note.")
        for item in selected:
            print(f"Topic: {item[1]}; review: {item[3]}; expires_unix: {item[7]:.0f}")
            print("Untrusted note (sanitized): " + display(item[2]))
        print("Local reviews and notes are unsigned; screening and redaction are incomplete.")
        _confirm(
            f"Type USE-EXPERIENCE {baseline_id} to approve exposure: ",
            f"USE-EXPERIENCE {baseline_id}",
        )
        if selected_experience() != selected:
            raise HarnessError("selected experience changed since display")
    _confirm(f"Type EDIT {baseline_id} to start: ", f"EDIT {baseline_id}")
    if selected and selected_experience() != selected:
        raise HarnessError("selected experience changed since display")

    def request_editor(request: dict) -> str:
        message = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
        return model.complete("planner", [{"role": "user", "content": message}]).text

    try:
        proposals = propose(
            store,
            baseline_id,
            task,
            (request_editor,),
            k=k,
            experience=tuple(item[2] for item in selected),
            reviewed_experience=bool(selected),
        )
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
    experience_topics: tuple[str, ...] = (),
) -> int:
    _editor_candidates_interactive(
        store,
        baseline_id,
        task_file,
        config_file,
        budget_id,
        k,
        task_id=task_id,
        experience_topics=experience_topics,
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
    from .task_screen import screen_task

    screen_task(_task_input(store, None, task_id))
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
        selection = input("Type SELECT ID [ID ...], COMPOSE ID ID [ID ...], or CANCEL: ").strip()
    except (EOFError, KeyboardInterrupt):
        raise HarnessError(
            "workflow cancelled after editor; generated objects may remain"
        ) from None
    if len(selection) > 1024:
        raise HarnessError("workflow cancelled after editor; generated objects may remain")
    words = selection.split()
    if (
        2 <= len(words) <= 6
        and words[0] == "SELECT"
        and len(set(words[1:])) == len(words) - 1
        and all(identifier in unique for identifier in words[1:])
    ):
        chosen = tuple(words[1:])
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
        chosen = (candidate,)
    else:
        raise HarnessError("workflow cancelled after editor; generated objects may remain")
    # Check the current lower bound again for the chosen comparison count.
    # This is only a snapshot, not a reservation or a completion guarantee.
    budget.checkpoint()
    usage = budget.snapshot()
    count = len(chosen)
    if (
        usage.stopped
        or usage.max_trials - usage.trials < count + 1
        or usage.max_judge_calls - usage.judge_calls < count
        or usage.max_model_calls - usage.model_calls < count + 1
    ):
        raise HarnessError(
            "insufficient remaining admissions for selected candidates; no plan created"
        )
    print(
        f"Selected {count} candidate(s); minimum remaining admissions: "
        f"trials={count + 1}, judge callbacks={count}, model calls={count + 1}."
    )
    print("This check reserves nothing; trials can require more calls or stop early.")
    record = create_plan(store, baseline_id, chosen, None, commit, budget_id, task_id=task_id)
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


def record_experience_interactive(store: HarnessStore, lineage, topic: str, review_id: str) -> None:
    """Confirm a human-authored observation; never send it to a model."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise HarnessError("experience recording requires an interactive terminal")
    from .cli import _safe, _show_review
    from .experience import _approved, _validate_text, _validate_topic
    from .experience_cli_store import open_cli_experience

    _validate_topic(topic)
    reviews = ReviewLedger(store)
    record = _approved(reviews, review_id)
    _show_review(store, record, lineage)
    print(
        "Write one line of your own observation; it is retained in plaintext, not sent to a model."
    )
    print(
        "Secret detection is incomplete. Same-topic notes can be superseded but remain in history."
    )
    try:
        text = input("Observation: ")
    except (EOFError, KeyboardInterrupt):
        raise HarnessError("experience recording cancelled") from None
    _validate_text(text)
    print(f"Topic: {topic}; observation (sanitized): {_safe(text)}")
    print("This local note is untrusted, not a safety rule, proof of improvement or authorization.")
    _confirm(f"Type SAVE {topic} {review_id} to record: ", f"SAVE {topic} {review_id}")
    if reviews.get(review_id) != record:
        raise HarnessError("review changed since display")
    with open_cli_experience(store, reviews, create=True) as library:
        # No lock is held while waiting for the operator. Recheck after locking.
        if reviews.get(review_id) != record:
            raise HarnessError("review changed since display")
        result = library.record(topic, text, review_id, reviewed=True)
    print(f"Recorded experience: topic={topic} operation={result['op']}")
    print("No model call, prompt change, selection or adoption occurred.")


def reflect_experience_interactive(
    store: HarnessStore,
    lineage,
    topic: str,
    review_id: str,
    observation_file: str,
    config_file: str,
    budget_id: str,
) -> None:
    """Generate an untrusted lesson hypothesis, with separately confirmed persistence."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise HarnessError("reflection requires an interactive terminal")
    from .cli import _safe, _show_review
    from .editor import _unique
    from .experience import MAX_LESSON_BYTES, _approved, _validate_text, _validate_topic
    from .experience_cli_store import open_cli_experience

    _validate_topic(topic)
    reviews = ReviewLedger(store)
    record = _approved(reviews, review_id)
    baseline = store.get_manifest(record.baseline_id)
    packaged = default_manifest()
    if (
        baseline.schema_version != packaged.schema_version
        or baseline.components != packaged.components
    ):
        raise HarnessError("reflection requires the unchanged packaged baseline")
    observation = _read_text(observation_file, MAX_LESSON_BYTES + 1)
    observation = observation.removesuffix("\n")
    _validate_text(observation)
    config = _config(config_file)
    budget = DurableBudget(store, budget_id)
    budget.require_available(trials=0, model_calls=1, judge_calls=0)
    task = "Draft one tentative lesson from the operator supplied observation."
    try:
        _review_input(observation, config.provider.api_key)
        model = bind_probe_model(
            store, record.baseline_id, record.baseline_id, task, config, max_calls=1, budget=budget
        )
    except ProbeModelError:
        raise HarnessError("reflection preflight rejected sensitive or invalid input") from None
    try:
        endpoint = urlsplit(config.provider.base_url).hostname or "provider default"
    except ValueError:
        raise HarnessError("invalid provider endpoint") from None

    def display(value: str) -> str:
        value = redact_text(value)
        if config.provider.api_key:
            value = value.replace(config.provider.api_key, "[REDACTED]")
        return _safe(value)

    _show_review(store, record, lineage)
    print("Operator observation (sanitized; review the source separately):\n" + _safe(observation))
    print(
        f"Provider host: {display(endpoint)}; model: {display(config.provider.model)}; budget: {budget.id}"
    )
    print(
        "One model call sends the observation, topic, recorded winner/confidence and baseline planner identity."
    )
    print("The full trajectory is not retained or sent. The model cannot verify the observation.")
    print("Provider exposure may disclose data and cost money; admission is not a token/USD cap.")
    print(
        "The record is unsigned. Generated text is untrusted and may invent or contain instructions."
    )
    _confirm(f"Type REFLECT {review_id} to send: ", f"REFLECT {review_id}")
    if reviews.get(review_id) != record:
        raise HarnessError("review changed since display")
    # Freeze the displayed file contents; changes after confirmation abort before sending.
    reread = _read_text(observation_file, MAX_LESSON_BYTES + 1)
    reread = reread.removesuffix("\n")
    if reread != observation:
        raise HarnessError("observation changed since display")
    request = {
        "topic": topic,
        "observation": observation,
        "recorded_winner": record.judge_winner,
        "recorded_confidence": record.judge_confidence,
        "instructions": "Return JSON with exactly lesson: one brief tentative, non-sensitive observation. Do not invent evidence.",
    }
    try:
        response = model.complete(
            "planner", [{"role": "user", "content": json.dumps(request, ensure_ascii=False)}]
        ).text
        value = json.loads(response, object_pairs_hook=_unique)
        if type(value) is not dict or set(value) != {"lesson"}:
            raise ValueError("unexpected response")
        draft = value["lesson"]
        _validate_text(draft)
        if "[REDACTED]" in draft:
            raise ValueError("redacted model output is not accepted as a lesson")
        text = "Model-drafted hypothesis: " + draft
        _validate_text(text)
    except Exception:  # noqa: BLE001 — untrusted output and provider errors are not displayed
        raise HarnessError("reflection failed; inspect budget before retrying") from None
    print(
        "Draft lesson (untrusted, sanitized; independently verify before saving):\n" + _safe(text)
    )
    print(
        "Saving may supersede an existing topic and retains plaintext history; it does not authorize adoption."
    )
    _confirm(f"Type SAVE {topic} {review_id} to record: ", f"SAVE {topic} {review_id}")
    if reviews.get(review_id) != record:
        raise HarnessError("review changed since display")
    with open_cli_experience(store, reviews, create=True) as library:
        if reviews.get(review_id) != record:
            raise HarnessError("review changed since display")
        result = library.record(topic, text, review_id, reviewed=True)
    print(f"Recorded untrusted model-drafted experience: topic={topic} operation={result['op']}")
    print("No editor prompt, trial, ref or adoption changed.")


def compose_recorded_interactive(
    store: HarnessStore,
    campaign_id: str,
    task_id: str,
    review_ids: tuple[str, ...],
    *,
    resolve_conflicts: bool = False,
    test_budget: str | None = None,
    test_config: str | None = None,
    test_repo: str | None = None,
) -> int:
    """Inspect, compose and optionally plan/test with separate confirmations."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise HarnessError("recorded composition requires an interactive terminal")
    from .cli import _diff_objects, _safe
    from .evidence_composition import prepare_recorded_composition

    options = (test_budget, test_config, test_repo)
    testing = any(value is not None for value in options)
    if testing and any(type(value) is not str or not value for value in options):
        raise HarnessError(
            "composite testing requires --test-budget, --test-config and --test-repo"
        )
    inputs = prepare_recorded_composition(store, campaign_id, task_id, review_ids)
    campaign = inputs.campaign
    if testing:
        if not Path(test_repo).expanduser().is_dir():
            raise HarnessError("composite test repository directory is missing")
        cap = DurableBudget(store, test_budget)
        cap.require_available(trials=2, model_calls=2, judge_calls=1)
        config = _config(test_config)
        try:
            bind_probe_model(
                store, campaign.baseline, campaign.baseline, inputs.task, config, budget=cap
            )
        except ProbeModelError:
            raise HarnessError(
                "composite test preflight rejected invalid or sensitive inputs"
            ) from None
    print(f"Completed campaign: {campaign.id}; baseline: {campaign.baseline}")
    print(f"Commit: {campaign.commit}; task SHA-256: {campaign.task_sha256}")
    print(f"Recorded workspace SHA-256: {inputs.reviews[0].workspace_sha256}")
    print("Task (sanitized):\n" + _safe(inputs.task))
    print(
        "These local records are unsigned and can be fabricated; full trajectories are not retained."
    )
    print(
        "A recorded preference or approval is not authenticated, an adoption gate, or proof of improvement."
    )
    for record in inputs.reviews:
        print(
            f"\nReview {record.id}; candidate {record.candidate_id}; state={record.state}; "
            f"recorded winner={record.judge_winner}; confidence={record.judge_confidence}"
        )
        print(_diff_objects(store, campaign.baseline, record.candidate_id), end="")
    print("\nThe human chooses inputs, including ties or losses; no automatic winner is selected.")
    if resolve_conflicts:
        print("Conflicts require local replacement diff files and a second confirmation.")
    else:
        print("Exact reconstructed diffs merge syntactically; conflicts abort.")
    print("No provider or Docker is used by composition.")
    print(
        "A combined candidate is untested and unadopted and may persist even after later failures."
    )
    if testing:
        print(
            "An optional composite test requires separate PLAN and RUN confirmations and may cost money."
        )
        print("The recorded workspace hash is unsigned; admission minima are not reservations.")
    _confirm(
        f"Type COMPOSE {campaign.id} to create an unadopted candidate: ", f"COMPOSE {campaign.id}"
    )
    # Local trusted databases are not one atomic transaction. Re-read and
    # revalidate all linked records and content after the operator's review.
    if prepare_recorded_composition(store, campaign_id, task_id, review_ids) != inputs:
        raise HarnessError("campaign, task or reviews changed since display")
    from .composer import preview_proposals

    preview = preview_proposals(store, campaign.baseline, inputs.proposals)
    selected_proposals = inputs.proposals
    if preview.conflicts:
        for conflict in preview.conflicts:
            print(
                f"Conflict: {conflict.path} between review {inputs.proposal_reviews[conflict.first]} "
                f"and review {inputs.proposal_reviews[conflict.second]}"
            )
        if not resolve_conflicts:
            raise HarnessError("composition conflicts; no composite candidate created")
        from .conflict_resolution import draft_conflict_resolutions

        print(
            "Each local patch replaces ALL selected edits for its path, including non-conflicting edits."
        )
        print(
            "Supply an exact base-relative unified diff. Review full files separately; redaction is incomplete."
        )

        cancelled = False

        def local_patch(request: dict) -> str:
            nonlocal cancelled
            try:
                filename = input(
                    f"Replacement patch file for {request['path']} (or CANCEL): "
                ).strip()
            except (EOFError, KeyboardInterrupt):
                cancelled = True
                raise HarnessError("campaign cancelled") from None
            if not filename or filename.upper() == "CANCEL":
                cancelled = True
                raise HarnessError("campaign cancelled")
            return json.dumps(
                {"path": request["path"], "diff": _read_text(filename, MAX_PATCH_BYTES)}
            )

        try:
            draft = draft_conflict_resolutions(
                store,
                campaign.baseline,
                inputs.proposals,
                local_patch,
                reviewed_callback_inputs=True,
            )
        except HarnessError:
            if cancelled:
                raise HarnessError("campaign cancelled") from None
            raise
        for proposal in draft.proposals:
            if proposal.path in draft.replaced_paths:
                print(
                    f"\nReplacement diff for {proposal.path} (redacted display; inspect full file too):"
                )
                print(_safe(redact_text(proposal.diff)), end="")
        print("These patches are untrusted and untested. Review all retained and replaced edits.")
        _confirm(f"Type RESOLVE {campaign.id} to create the candidate: ", f"RESOLVE {campaign.id}")
        if prepare_recorded_composition(store, campaign_id, task_id, review_ids) != inputs:
            raise HarnessError("campaign, task or reviews changed since display")
        selected_proposals = draft.proposals
    result = compose_proposals(store, campaign.baseline, selected_proposals)
    if result.conflicts:
        raise HarnessError("composition conflicts; no composite candidate created")
    if result.candidate_id is None:
        raise HarnessError("composition did not produce a candidate")
    review_candidate(store, campaign.baseline, result.candidate_id)
    print(f"\nUnadopted composite candidate: {result.candidate_id}")
    print("Composite diff (sanitized; untrusted and not behaviorally tested):")
    print(_diff_objects(store, campaign.baseline, result.candidate_id), end="")
    print(
        "No plan, trial, approval or adoption occurred. A separate reviewed comparison is required."
    )
    if not testing:
        return 0
    print("The candidate already exists; cancellation may leave it in the store.")
    print("The recorded workspace hash will be bound to the plan; it is unsigned and untrusted.")
    print("Cancellation can leave a ready plan. Interrupted runs cannot be automatically resumed.")
    _confirm(
        f"Type PLAN {result.candidate_id} to create a test plan: ", f"PLAN {result.candidate_id}"
    )
    if prepare_recorded_composition(store, campaign_id, task_id, review_ids) != inputs:
        raise HarnessError("campaign, task or reviews changed since display")
    cap.require_available(trials=2, model_calls=2, judge_calls=1)
    plan = create_plan(
        store,
        campaign.baseline,
        (result.candidate_id,),
        None,
        campaign.commit,
        test_budget,
        task_id=task_id,
        workspace_sha256=inputs.reviews[0].workspace_sha256,
    )
    print(f"Created composite test plan: {plan.id}; budget={test_budget}.")
    from .lineage import HarnessLineage

    adopted_id = HarnessLineage(store, read_only=True).resolve("refs/heads/adopted")
    return run_interactive(
        store,
        adopted_id,
        plan.id,
        None,
        test_config,
        test_repo,
        test_budget,
        task_id=task_id,
        expected_workspace_sha256=inputs.reviews[0].workspace_sha256,
    )


def canary_interactive(
    store: HarnessStore,
    baseline_id: str,
    candidate_id: str,
    config_file: str,
    repo: str,
    commit: str,
    budget_id: str,
    *,
    review_id: str | None = None,
) -> int:
    """Explicitly review and run fixed canaries; never authorize adoption."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise HarnessError("canary run requires an interactive terminal")
    from .canary import CASES, run_manual_canaries
    from .cli import _diff_objects, _safe

    review = None
    ledger = None
    if review_id is not None:
        ledger = ReviewLedger(store)
        review = ledger.get(review_id)
        if (
            review.source != "paired"
            or review.baseline_id != baseline_id
            or review.candidate_id != candidate_id
            or review.commit != commit
        ):
            raise HarnessError("paired review does not match the requested canary inputs")
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
    if review is not None:
        print(f"Advisory review: {review.id}; state={review.state}; evidence is unsigned.")
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
        expected_workspace_sha256=review.workspace_sha256 if review is not None else None,
    )
    for item in report.findings:
        print(f"{item.case_id}: baseline={item.reference}; candidate={item.candidate}")
    print(f"Canary result: {report.outcome}; workspace sha256: {report.workspace_sha256}")
    if review is not None:
        from .fusion import assess

        if ledger.get(review.id) != review:
            raise HarnessError("paired review changed while the canaries were running")
        advisory = assess(review, report)
        print(f"Advisory: {advisory.outcome}; basis: {advisory.basis}")
        print(
            "Advisory only; evidence and reviewers are not authenticated, and baseline freshness is not established."
        )
    print("Result is unsigned and is not an adoption authorization. No refs moved.")
    return 0 if report.outcome == "passed" else 1


def portability_interactive(
    store: HarnessStore,
    adopted_id: str,
    baseline_id: str,
    candidate_id: str,
    task_file: str | None,
    config_file: str,
    repo: str,
    commit: str,
    budget_id: str,
    image_ids: tuple[str, str],
    *,
    task_id: str | None = None,
) -> int:
    """Confirm two reviewed image comparisons with human judgments; never adopt."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise HarnessError("portability run requires an interactive terminal")
    from .cli import _diff_objects, _safe
    from .portability import run_portability_comparison, validate_image_ids

    validate_image_ids(image_ids)
    if type(commit) is not str or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", commit):
        raise HarnessError("commit must be a full lowercase Git object ID")
    if not Path(repo).expanduser().is_dir():
        raise HarnessError("repository directory is missing")
    baseline = store.get_manifest(baseline_id)
    packaged = default_manifest()
    if (
        baseline.schema_version != packaged.schema_version
        or baseline.components != packaged.components
    ):
        raise HarnessError("portability run requires the unchanged packaged baseline")
    if baseline_id == candidate_id:
        raise HarnessError("portability run requires a distinct candidate")
    review_candidate(store, baseline_id, candidate_id)
    task = _task_input(store, task_file, task_id)
    config = _config(config_file)
    if config.sandbox.network != "none" or config.sandbox.backend not in ("auto", "docker"):
        raise HarnessError("portability comparison requires Docker with networking disabled")
    budget = DurableBudget(store, budget_id)
    budget.checkpoint()
    try:
        bind_probe_model(store, baseline_id, baseline_id, task, config, budget=budget)
        bind_probe_model(store, baseline_id, candidate_id, task, config, budget=budget)
    except ProbeModelError:
        raise HarnessError("portability preflight rejected sensitive or invalid input") from None
    usage = budget.snapshot()
    if (
        usage.stopped
        or usage.max_trials - usage.trials < 4
        or usage.max_model_calls - usage.model_calls < 4
        or usage.max_judge_calls - usage.judge_calls < 2
    ):
        raise HarnessError(
            "portability requires at least four trial, four model and two judge admissions"
        )
    try:
        endpoint = urlsplit(config.provider.base_url).hostname or "provider default"
    except ValueError:
        raise HarnessError("invalid provider endpoint") from None

    def display(value: str) -> str:
        value = redact_text(value)
        if config.provider.api_key:
            value = value.replace(config.provider.api_key, "[REDACTED]")
        return _safe(value)

    print("Manual two-image portability comparison")
    print(f"Baseline: {baseline_id}\nCandidate: {candidate_id}")
    if baseline_id != adopted_id:
        print("WARNING: the test baseline is not the currently adopted baseline.")
    print(f"Profile A image: {image_ids[0]}\nProfile B image: {image_ids[1]}")
    print(f"Repository: {_safe(str(Path(repo).expanduser().absolute()))}; commit: {commit}")
    print(
        f"Provider: {display(config.provider.name)}; model: {display(config.provider.model)}; host: {display(endpoint)}"
    )
    print(
        f"Budget: {budget.id}; trials {usage.trials}/{usage.max_trials}; model calls {usage.model_calls}/{usage.max_model_calls}; judges {usage.judge_calls}/{usage.max_judge_calls}"
    )
    print(
        "Four trials and two human judgments; up to 16 model calls. Admission minimum is not a reservation."
    )
    print("Task (sanitized display):\n" + _safe(task))
    print("Candidate sanitized diff:\n" + _diff_objects(store, baseline_id, candidate_id), end="")
    print("Review and trust BOTH image contents, the commit, full endpoint and inputs separately.")
    print(
        "Images must exist locally. Docker daemon/image are trusted; no host fallback; tool network disabled."
    )
    print("After confirmation, both image IDs are checked locally; availability can change later.")
    print(
        "Provider and judge exposure may reveal data and cost money. No token/USD or hard-runtime cap."
    )
    print(
        "Image IDs do not establish distinct kernels, safety, evidence authenticity or authorization."
    )
    _confirm(f"Type PORTABILITY {candidate_id} to start: ", f"PORTABILITY {candidate_id}")

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

    report = run_portability_comparison(
        store,
        baseline_id,
        candidate_id,
        task,
        config,
        human_judge,
        image_ids=image_ids,
        repo=repo,
        commit=commit,
        budget=budget,
        reviewed_inputs=True,
        reviewed_judge_inputs=True,
        reviewed_images=True,
    )
    print(f"Portability result: {report.outcome}")
    for label, pair in (("A", report.first), ("B", report.second)):
        if pair is not None and pair.judgment is not None:
            print(
                f"Profile {label}: {pair.judgment.winner}; confidence is an unassessed placeholder."
            )
    print("Unsigned advisory only; no review recorded, no refs moved, no adoption authorized.")
    return 0 if report.outcome == "compared" else 1
