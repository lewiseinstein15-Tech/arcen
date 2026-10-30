"""One-shot headless entry point, using the server's existing turn loop.

JSON is an envelope, not a second event protocol: the canonical wire events are
embedded unchanged. Only the verified packaged adopted baseline may be selected;
candidate refs remain blocked. Workspaces are input-only Docker snapshots.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import threading
import uuid
from typing import Any

SCHEMA_VERSION = 1


def execute(
    goal: str,
    *,
    state: Any = None,
    workspace: str | None = None,
    harness: str | None = None,
    harness_store: str | None = None,
) -> dict:
    """Run the shared turn; only a verified packaged baseline may be selected."""
    # Import inside execute so invalid packaged resources are reported by the
    # headless error envelope instead of failing before main's error handler.
    from arcen.agents.draft import DIRECT_NO_PROVIDER_ANSWER, NO_PLAN_ANSWER, NO_PROVIDER_ANSWER
    from arcen.server.app import ServerState, run_turn

    refusals = {NO_PROVIDER_ANSWER, NO_PLAN_ANSWER, DIRECT_NO_PROVIDER_ANSWER}
    selected = None
    if harness is not None:
        from arcen.harness.selection import resolve_packaged_baseline

        selected = resolve_packaged_baseline(
            harness, "~/.arcen/harness" if harness_store is None else harness_store
        )
    elif harness_store is not None:
        raise ValueError("--harness-store requires --harness")
    if state is None:
        state = ServerState()
    if selected is not None:
        from arcen.harness.manifest import default_manifest
        from arcen.harness.resolver import default_prompts
        from arcen.llm.client import Client

        if state.manifest != default_manifest() or (
            state.llm is not None
            and (type(state.llm) is not Client or state.llm.prompts != default_prompts())
        ):
            raise ValueError("runtime client does not use the selected packaged harness")
    session_id = str(uuid.uuid4())
    run_id = f"r-{uuid.uuid4().hex[:12]}"
    state.run_flags[run_id] = threading.Event()
    try:
        run_turn(
            goal,
            session_id,
            run_id,
            state,
            workspace=workspace,
            harness_ref=f"sha256:{selected}" if selected is not None else None,
        )
        events = state.emitter_for(session_id).replay(0)
    finally:
        state.run_flags.pop(run_id, None)
    answer = next((e.get("text") for e in reversed(events) if e.get("type") == "answer"), None)
    terminal = next(
        (e for e in reversed(events) if e.get("type") in {"run.done", "run.error"}), None
    )
    error = None
    if terminal is None:
        status = "error"
        error = {"code": "MISSING_TERMINAL_EVENT", "message": "turn ended without a terminal event"}
    elif terminal["type"] == "run.error":
        status = "error"
        error = {"code": terminal.get("code"), "message": terminal.get("message")}
    elif answer in refusals:
        status = "failed"
        error = {"code": "TASK_REFUSED", "message": answer}
    else:
        status = terminal.get("status", "error")
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "session_id": session_id,
        "status": status,
        "answer": answer,
        "error": error,
        "events": events,
        "workspace_mode": "snapshot_requested" if workspace is not None else "empty",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="arcen run", description="Run one ARCEN turn without a TTY."
    )
    parser.add_argument("goal", help="the task or question to run")
    parser.add_argument(
        "--json", action="store_true", help="print the complete result envelope as JSON"
    )
    parser.add_argument(
        "--harness", help="select the verified packaged baseline: adopted or refs/heads/adopted"
    )
    parser.add_argument(
        "--harness-store", help="trusted local harness store (default: ~/.arcen/harness)"
    )
    parser.add_argument(
        "--workspace", help="copy a bounded input-only workspace snapshot into the container"
    )
    args = parser.parse_args(argv)
    if not args.goal.strip():
        parser.error("goal must not be empty")
    if args.harness is not None and args.harness not in ("adopted", "refs/heads/adopted"):
        parser.error("candidate selection unavailable; no harness reference was applied")
    if args.harness_store is not None and args.harness is None:
        parser.error("--harness-store requires --harness")
    try:
        # Third-party libraries sometimes print progress. Keep JSON stdout a
        # single parseable document, including in non-interactive scripts.
        with contextlib.redirect_stdout(sys.stderr):
            result = execute(
                args.goal,
                workspace=args.workspace,
                harness=args.harness,
                harness_store=args.harness_store,
            )
    except Exception as exc:  # noqa: BLE001 — one-shot CLI reports a failure, never success
        result = {
            "schema_version": SCHEMA_VERSION,
            "run_id": None,
            "session_id": None,
            "status": "error",
            "answer": None,
            "error": {"code": "HEADLESS_FAILED", "message": str(exc)},
            "events": [],
            "workspace_mode": "snapshot_requested" if args.workspace is not None else "empty",
        }
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    elif result["answer"]:
        print(result["answer"])
    elif result["error"]:
        print(f"{result['error']['code']}: {result['error']['message']}", file=sys.stderr)
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
