"""One-shot headless entry point, using the server's existing turn loop.

JSON is an envelope, not a second event protocol: the canonical wire events are
embedded unchanged. Harness refs are rejected until the harness store exists.
Workspaces are copied into Docker as bounded input-only snapshots, never mounted.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import threading
import uuid
from typing import Any

from arcen.agents.draft import DIRECT_NO_PROVIDER_ANSWER, NO_PLAN_ANSWER, NO_PROVIDER_ANSWER

SCHEMA_VERSION = 1
REFUSALS = {NO_PROVIDER_ANSWER, NO_PLAN_ANSWER, DIRECT_NO_PROVIDER_ANSWER}


def execute(goal: str, *, state: Any = None, workspace: str | None = None) -> dict:
    """Run the same server turn and summarize its frozen wire events."""
    from arcen.server.app import ServerState, run_turn

    if state is None:
        state = ServerState()
    session_id = str(uuid.uuid4())
    run_id = f"r-{uuid.uuid4().hex[:12]}"
    state.run_flags[run_id] = threading.Event()
    try:
        run_turn(goal, session_id, run_id, state, workspace=workspace)
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
    elif answer in REFUSALS:
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
        "--harness", help="harness reference (not available until the harness store lands)"
    )
    parser.add_argument(
        "--workspace", help="copy a bounded input-only workspace snapshot into the container"
    )
    args = parser.parse_args(argv)
    if not args.goal.strip():
        parser.error("goal must not be empty")
    if args.harness is not None:
        parser.error("--harness is not available yet; no harness reference was applied")
    try:
        # Third-party libraries sometimes print progress. Keep JSON stdout a
        # single parseable document, including in non-interactive scripts.
        with contextlib.redirect_stdout(sys.stderr):
            result = execute(args.goal, workspace=args.workspace)
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
