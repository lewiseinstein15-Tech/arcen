"""ARCEN — sub-agent pool (BACKEND-SPEC Part 1 L2 / Part 2 row 4).

Pulled from CrewAI (agent.py + task.py) — the crew spawn/task model where
named agents carry a task and report results back.

Edited per the Pull Map:
- depth cap (default 2): a sub-agent may spawn children, grandchildren
  never — no runaway recursion;
- concurrency cap (default 8): the pool refuses work beyond the cap;
- per-sub-agent naming for the task at hand (TEST-READER, MIGRATOR, ...);
- emits ``spawn`` / ``spawn.done`` on the frozen event schema.

Only 3 core agents exist. A sub-agent is not a new brain: it is a task
scope + a name + FORGE steps, torn down when done.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable

from arcen.agents.forge import ForgeExecutor
from arcen.stream.events import Event, Spawn, SpawnDone, to_line
from arcen.tools.registry import Registry, load_builtin

DEFAULT_MAX_DEPTH = 2
DEFAULT_MAX_CONCURRENT = 8


class DepthCapExceeded(Exception):
    pass


class ConcurrencyCapExceeded(Exception):
    pass


class SubAgent:
    """One spawned worker: a name, a task, and the steps to run."""

    def __init__(self, name: str, task: str, depth: int, forge: ForgeExecutor) -> None:
        self.name = name
        self.task = task
        self.depth = depth
        self.forge = forge

    def run(self, steps: list[dict]) -> dict:
        """Run steps sequentially through FORGE. Returns the done payload."""
        started = time.monotonic()
        calls = 0
        ok = True
        for step in steps:
            events = self.forge.execute_step(step)
            calls += 1
            if not events[1].ok:
                ok = False
                break
        return {
            "name": self.name,
            "ok": ok,
            "calls": calls,
            "duration_s": round(time.monotonic() - started, 4),
        }


class SubAgentPool:
    """Spawns sub-agents, enforces the two caps, emits spawn events."""

    def __init__(
        self,
        registry: Registry,
        emit: Callable[[Event], None] | None = None,
        max_depth: int = DEFAULT_MAX_DEPTH,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
        forge: ForgeExecutor | None = None,
    ) -> None:
        self.registry = registry
        self.emit = emit
        self.max_depth = max_depth
        self.max_concurrent = max_concurrent
        self._forge = forge
        self._active = 0
        self._lock = threading.Lock()
        self.spawned: list[SubAgent] = []

    def spawn(
        self,
        parent: str,
        name: str,
        task: str,
        depth: int,
        steps: list[dict],
    ) -> dict:
        """Spawn → run → done. Returns {ok, calls, duration_s} (or denial)."""
        if depth > self.max_depth:
            raise DepthCapExceeded(
                f"sub-agent {name!r} at depth {depth} exceeds max_depth={self.max_depth}"
            )
        with self._lock:
            if self._active >= self.max_concurrent:
                raise ConcurrencyCapExceeded(
                    f"sub-agent pool at max_concurrent={self.max_concurrent}"
                )
            self._active += 1
        try:
            spawn_event = Spawn(seq=0, parent=parent, name=name, task=task, depth=depth, ts=0.0)
            self._emit(spawn_event)

            forge = self._forge or ForgeExecutor(self.registry, emit=self.emit)
            agent = SubAgent(name=name, task=task, depth=depth, forge=forge)
            self.spawned.append(agent)
            result = agent.run(steps)

            done = SpawnDone(
                seq=0,
                name=name,
                ok=result["ok"],
                calls=result["calls"],
                duration_s=result["duration_s"],
                ts=0.0,
            )
            self._emit(done)
            return result
        finally:
            with self._lock:
                self._active -= 1
            # teardown: the sub-agent is done and dropped — nothing retained

    def _emit(self, event: Event) -> None:
        if self.emit is not None:
            self.emit(event)


def main(argv: list[str]) -> int:
    """`python -m arcen.subagents.agent` — spawn RESEARCH, wait for done."""
    registry = load_builtin()
    sink: list[Event] = []
    pool = SubAgentPool(registry, emit=sink.append)
    result = pool.spawn(
        parent="DRAFT",
        name="RESEARCH",
        task="survey the repository layout",
        depth=1,
        steps=[
            {"id": 1, "tool": "bash", "args": {"cmd": "ls -1 | head -5"}},
            {"id": 2, "tool": "bash", "args": {"cmd": "echo research-complete"}},
        ],
    )
    for event in sink:
        print(to_line(event))
    print(to_line_safe(result))
    return 0 if result["ok"] else 1


def to_line_safe(result: dict) -> str:
    import json

    return json.dumps({"spawn.done": result}, ensure_ascii=False)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
