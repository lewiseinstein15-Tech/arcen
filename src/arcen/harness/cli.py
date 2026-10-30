"""Harness metadata and opt-in interactive campaigns; adoption is disabled."""

from __future__ import annotations

import argparse
import difflib
import sqlite3
import sys
import unicodedata
from importlib import resources
from pathlib import Path

from .lineage import HarnessLineage
from .manifest import MAX_COMPONENT_BYTES, default_manifest
from .resolver import HarnessError
from .store import HarnessStore


def _existing(root: str) -> tuple[HarnessStore, HarnessLineage]:
    base = Path(root).expanduser()
    for path in (base, base / "objects", base / "objects/sha256"):
        if path.is_symlink() or not path.is_dir():
            raise HarnessError("store is missing or invalid; run harness init first")
    db_path = base / "lineage.sqlite3"
    if db_path.is_symlink() or not db_path.is_file():
        raise HarnessError("store database is missing or invalid; run harness init first")
    store = HarnessStore(base)
    return store, HarnessLineage(store, read_only=True)


def _init(root: str) -> str:
    store = HarnessStore(root)
    manifest = default_manifest()
    package = resources.files("arcen")
    for name, digest in manifest.components.items():
        with package.joinpath(*name.split("/")).open("rb") as stream:
            raw = stream.read(MAX_COMPONENT_BYTES + 1)
        if store.put_blob(raw) != digest:
            raise HarnessError(f"packaged component changed: {name}")
    object_id = store.put_manifest(manifest)
    HarnessLineage(store).initialize_baseline(object_id)
    return object_id


def _doctor(root: str) -> dict[str, int]:
    store, db = _existing(root)
    result = db.audit()
    objects = list(store.objects.iterdir())
    for item in objects:
        # A stale/foreign file, symlink, or corrupt object is an error.
        store.get_blob(item.name)
    result["objects"] = len(objects)
    return result


def _safe(text: str) -> str:
    # A stored candidate is untrusted display data: do not execute ANSI or
    # bidirectional terminal controls while showing a diff.
    return "".join(
        char if char in "\n\t" or unicodedata.category(char) not in {"Cc", "Cf"} else "�"
        for char in text
    )


def _diff(root: str, ref: str) -> str:
    store, db = _existing(root)
    return _diff_objects(store, db.resolve("refs/heads/adopted"), db.resolve(ref))


def _diff_objects(store: HarnessStore, baseline_id: str, candidate_id: str) -> str:
    baseline = store.get_manifest(baseline_id)
    candidate = store.get_manifest(candidate_id)
    output = []
    if baseline.model_pin != candidate.model_pin:
        output.append(f"model pin: {_safe(baseline.model_pin)} -> {_safe(candidate.model_pin)}\n")
    for name in sorted(baseline.components):
        old_hash, new_hash = baseline.components[name], candidate.components[name]
        if old_hash == new_hash:
            continue
        try:
            old = _safe(store.get_blob(old_hash).decode("utf-8")).splitlines(keepends=True)
            new = _safe(store.get_blob(new_hash).decode("utf-8")).splitlines(keepends=True)
        except UnicodeDecodeError as exc:
            raise HarnessError(f"non-UTF-8 component: {name}") from exc
        output.extend(
            difflib.unified_diff(old, new, fromfile=f"baseline/{name}", tofile=f"candidate/{name}")
        )
        if sum(len(x) for x in output) > MAX_COMPONENT_BYTES:
            raise HarnessError("diff exceeds display limit")
    return "".join(output) if output else "No differences.\n"


def _show_review(store: HarnessStore, record, lineage: HarnessLineage) -> None:
    print(f"Review: {record.id}  state={record.state}  evidence={record.source}")
    print(f"Baseline: {record.baseline_id}\nCandidate: {record.candidate_id}")
    if lineage.resolve("refs/heads/adopted") != record.baseline_id:
        print("WARNING: reviewed baseline is not the currently adopted baseline.")
    if record.source == "paired":
        print(f"Commit: {record.commit}  workspace sha256: {record.workspace_sha256}")
        print(f"Judge: {record.judge_winner}  confidence={record.judge_confidence}")
        print("Paired evidence is locally supplied, not authenticated or a safety proof.")
    if record.reviewer is not None:
        print(f"Reviewer: {_safe(record.reviewer)}  note: {_safe(record.note or '')}")
    print("\nSanitized component diff:")
    print(_diff_objects(store, record.baseline_id, record.candidate_id), end="")
    print("\nNo decision here can select, approve for execution, or adopt this candidate.")


def _review_command(args) -> None:
    from .review import ReviewLedger

    store, lineage = _existing(args.store)
    ledger = ReviewLedger(store, create=args.review_command == "open")
    if args.review_command == "open":
        record = ledger.request(args.baseline, args.candidate)
        print(f"Opened static review: {record.id}")
        print("No paired evidence; approval and adoption are unavailable.")
    elif args.review_command == "list":
        records = ledger.list()
        if not records:
            print("No review records.")
        for item in records:
            print(f"{item.id}  {item.state}  {item.source}  {item.candidate_id}")
        print("Local review records are not authenticated; adoption remains disabled.")
    elif args.review_command == "show":
        _show_review(store, ledger.get(args.id), lineage)
    else:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise HarnessError("review decision requires an interactive terminal")
        record = ledger.get(args.id)
        _show_review(store, record, lineage)
        action = "APPROVE" if args.review_command == "approve" else "REJECT"
        try:
            confirmation = input(f"Type {action} {record.id} to record this review decision: ")
        except EOFError:
            raise HarnessError("review decision cancelled") from None
        if confirmation.strip() != f"{action} {record.id}":
            raise HarnessError("review decision cancelled")
        decided = ledger.resolve(
            record.id,
            "approved" if action == "APPROVE" else "rejected",
            args.reviewer,
            args.note,
            saw_diff=True,
            expected=record,
        )
        print(f"Recorded {decided.state}; candidate was not adopted.")


def _campaign_command(args) -> int:
    from .campaign_journal import CampaignJournal

    store, lineage = _existing(args.store)
    if args.campaign_command == "plan":
        from .manual_cli import create_plan

        record = create_plan(
            store, args.baseline, tuple(args.candidate), args.task_file, args.commit, args.budget
        )
        print(f"Campaign plan: {record.id}  state={record.state}  budget={record.budget_id}")
        print("Metadata only; no provider calls, execution or adoption occurred.")
        return 0
    if args.campaign_command == "run":
        from .manual_cli import run_interactive

        return run_interactive(
            store,
            lineage.resolve("refs/heads/adopted"),
            args.id,
            args.task_file,
            args.config,
            args.repo,
            args.budget,
        )
    journal = CampaignJournal(store)
    record = (
        journal.request_stop(args.id) if args.campaign_command == "stop" else journal.get(args.id)
    )
    print(f"Campaign: {record.id}  state={record.state}  phase={record.phase}")
    print(
        f"Completed: {record.cursor}/{len(record.candidates)}  stop requested: {record.stop_requested}"
    )
    print(
        f"Baseline: {record.baseline}\nCommit: {record.commit}\nTask SHA-256: {record.task_sha256}"
    )
    print(f"Budget: {record.budget_id or 'unbound legacy plan'}")
    for candidate, review_id in zip(record.candidates, record.reviews):
        print(f"Review: {review_id}  candidate: {candidate}")
    print("Metadata only; no adoption or safe automatic resume. In-flight work may continue.")
    return 0


def _budget_command(args) -> None:
    from .durable_budget import DurableBudget

    store, _ = _existing(args.store)
    if args.budget_command == "create":
        budget = DurableBudget.create(
            store,
            max_trials=args.trials,
            max_model_calls=args.model_calls,
            max_judge_calls=args.judge_calls,
            admission_seconds=args.seconds,
        )
    else:
        budget = DurableBudget(store, args.id)
        if args.budget_command == "stop":
            budget.stop()
    state = budget.snapshot()
    print(f"Budget: {budget.id}  stopped={state.stopped}  reason={state.reason or 'open'}")
    print(
        f"Limits: trials={state.max_trials}  model calls={state.max_model_calls}  judge callbacks={state.max_judge_calls}"
    )
    print(f"Time until admission cutoff: {state.admission_seconds_remaining:.1f}s")
    print(
        f"Admitted: trials={state.trials}  model calls={state.model_calls}  judge callbacks={state.judge_calls}"
    )
    print("Admission accounting only; no token/USD cap or in-flight cancellation.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arcen harness")
    parser.add_argument("--store", default="~/.arcen/harness", help="trusted local store directory")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="initialize packaged baseline metadata")
    commands.add_parser("doctor", help="verify stored objects, refs and lineage")
    diff = commands.add_parser("diff", help="compare a candidate to baseline")
    diff.add_argument("ref", help="candidate ref, e.g. refs/candidates/example")
    rollback = commands.add_parser("rollback", help="unavailable until adoption gates exist")
    rollback.add_argument("ref", help="target ref (not applied yet)")
    baseline = commands.add_parser("pin-baseline", help="create an unadopted fixed-model baseline")
    baseline.add_argument("pin", help="fixed:provider:model")
    patch = commands.add_parser(
        "import-patch", help="create an unadopted candidate from a reviewed diff"
    )
    patch.add_argument("baseline")
    patch.add_argument("path", help="allowlisted component path")
    patch.add_argument("patch_file")
    review = commands.add_parser("review", help="record human review; adoption remains disabled")
    review_commands = review.add_subparsers(dest="review_command", required=True)
    review_open = review_commands.add_parser(
        "open", help="open a static review of two stored manifest IDs"
    )
    review_open.add_argument("baseline")
    review_open.add_argument("candidate")
    review_commands.add_parser("list", help="list recent review records")
    show = review_commands.add_parser("show", help="show review and sanitized diff")
    show.add_argument("id")
    for action in ("approve", "reject"):
        decision = review_commands.add_parser(
            action, help="interactive review decision; never adopts"
        )
        decision.add_argument("id")
        decision.add_argument(
            "--reviewer", required=True, help="local reviewer label (not authenticated)"
        )
        decision.add_argument(
            "--note", default="", help="optional plaintext note; do not include secrets"
        )
    campaign = commands.add_parser(
        "campaign", help="plan, run, inspect or stop a manual comparison"
    )
    campaign_commands = campaign.add_subparsers(dest="campaign_command", required=True)
    for action in ("status", "stop"):
        command = campaign_commands.add_parser(action)
        command.add_argument("id")
    plan = campaign_commands.add_parser(
        "plan", help="record a manual comparison plan; no execution"
    )
    plan.add_argument("--baseline", required=True)
    plan.add_argument("--candidate", required=True, action="append")
    plan.add_argument("--task-file", required=True)
    plan.add_argument("--commit", required=True)
    plan.add_argument("--budget", required=True, help="durable admission budget ID")
    run = campaign_commands.add_parser("run", help="interactive reviewed run with human A/B judge")
    run.add_argument("id")
    run.add_argument("--task-file", required=True)
    run.add_argument("--config", required=True)
    run.add_argument("--repo", required=True)
    run.add_argument("--budget", required=True)
    budget = commands.add_parser("budget", help="create, inspect or stop an admission budget")
    budget_commands = budget.add_subparsers(dest="budget_command", required=True)
    for action in ("status", "stop"):
        command = budget_commands.add_parser(action)
        command.add_argument("id")
    create_budget = budget_commands.add_parser("create", help="create durable admission limits")
    create_budget.add_argument("--trials", type=int, required=True)
    create_budget.add_argument("--model-calls", type=int, required=True)
    create_budget.add_argument("--judge-calls", type=int, required=True)
    create_budget.add_argument("--seconds", type=float, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            print(f"Initialized packaged baseline: {_init(args.store)}")
            print("Metadata only; candidate selection and adoption remain disabled.")
        elif args.command == "doctor":
            stats = _doctor(args.store)
            print(
                "Store integrity OK: " + ", ".join(f"{key}={value}" for key, value in stats.items())
            )
            print("Hashes do not authenticate provenance; candidate selection remains disabled.")
        elif args.command == "diff":
            print(_diff(args.store, args.ref), end="")
        elif args.command == "pin-baseline":
            from .manual_cli import pin_baseline

            store, lineage = _existing(args.store)
            identifier = pin_baseline(store, lineage.resolve("refs/heads/adopted"), args.pin)
            print(f"Unadopted pinned baseline: {identifier}")
        elif args.command == "import-patch":
            from .manual_cli import import_patch

            store, _ = _existing(args.store)
            identifier = import_patch(store, args.baseline, args.path, args.patch_file)
            print(f"Unadopted candidate: {identifier}")
        elif args.command == "review":
            _review_command(args)
        elif args.command == "campaign":
            return _campaign_command(args)
        elif args.command == "budget":
            _budget_command(args)
        else:
            raise HarnessError(
                "rollback unavailable: no adoption/approval safety gate is implemented"
            )
    except (HarnessError, OSError, sqlite3.Error) as exc:
        print(f"harness: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
