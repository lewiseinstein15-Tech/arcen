"""ARCEN — FORGE, the executor (BACKEND-SPEC Part 1 / Part 2 row 2).

Pulled from OpenHands (controller/agent.py + tools/) — the agent state
machine and the run-loop-over-actions pattern.

Edited per the Pull Map:
- reduced to step-at-a-time: one tool call per ``execute_step``, state
  returns to idle after every step (no autonomous batching);
- emits ``command`` / ``command.done`` on the frozen event schema, plus
  ``file.diff`` when a file mutation actually changed bytes;
- every call routes through the Tool registry (Part 3) — FORGE never
  touches tool implementations directly.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable

from arcen.stream.events import Command, CommandDone, Event, FileDiff, to_line
from arcen.tools.registry import Registry, load_builtin

# OpenHands AgentState, reduced to the three states a step-at-a-time
# executor actually occupies.
IDLE = "idle"
RUNNING = "running"
ERROR = "error"

DIFF_TOOLS = {"file.write", "file.edit", "file.append"}


def _read(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


class ForgeExecutor:
    """Runs tools, one step at a time. Returns observations as events."""

    def __init__(
        self,
        registry: Registry,
        emit: Callable[[Event], None] | None = None,
    ) -> None:
        self.registry = registry
        self.emit = emit
        self.state: str = IDLE
        self.steps_executed: int = 0

    def execute_step(self, step: dict) -> list[Event]:
        """Exactly one tool call per invocation. command → command.done."""
        if self.state == RUNNING:
            raise RuntimeError("FORGE is step-at-a-time; a step is already running")
        step_id = int(step.get("id", 0))
        tool = step.get("tool") or "bash"
        args = step.get("args") or {}

        self.state = RUNNING
        command = Command(seq=0, agent="FORGE", step=step_id, tool=tool, args=args, ts=0.0)

        before = self._capture_before(tool, args)
        started = time.monotonic()
        envelope = self.registry.dispatch(tool, args)
        duration = round(time.monotonic() - started, 4)

        done = CommandDone(
            seq=0,
            step=step_id,
            ok=bool(envelope.get("ok")),
            result=envelope.get("result"),
            duration_s=duration,
            ts=0.0,
        )
        if envelope.get("error"):
            done.result = {"error": envelope["error"], "detail": envelope.get("result")}

        events: list[Event] = [command, done]

        diff = self._diff_after(tool, args, before)
        if diff is not None:
            events.append(diff)

        self.steps_executed += 1
        self.state = IDLE if done.ok else ERROR
        for e in events:
            if self.emit is not None:
                self.emit(e)
        return events

    # -- file.diff support (spec row 9) -------------------------------------
    def _capture_before(self, tool: str, args: dict) -> str | None:
        if tool in DIFF_TOOLS and isinstance(args.get("path"), str):
            return _read(args["path"])
        return None

    def _diff_after(self, tool: str, args: dict, before: str | None) -> FileDiff | None:
        if tool not in DIFF_TOOLS:
            return None
        path = args.get("path")
        if not isinstance(path, str):
            return None
        after = _read(path)
        if before == after:
            return None
        import difflib

        patch = "".join(
            difflib.unified_diff(
                (before or "").splitlines(keepends=True),
                (after or "").splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
        return FileDiff(seq=0, path=path, patch=patch, ts=0.0)


def main(argv: list[str]) -> int:
    """`python -m arcen.agents.forge` — one demo step, NDJSON on stdout."""
    registry = load_builtin()
    forge = ForgeExecutor(registry)
    step = {"id": 1, "title": "prove the executor runs", "tool": "bash", "args": {"cmd": "echo forge-online"}}
    for event in forge.execute_step(step):
        print(to_line(event))
    return 0 if forge.state == IDLE else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
