"""T-011 / Test-plan T-10 — sub-agent spawner (BACKEND-SPEC Part 1).

Proves: spawn → done; depth cap enforced at max_depth; concurrency
capped; spawn/spawn.done events on the frozen schema.
"""

import threading

import pytest

from arcen.subagents.agent import (
    ConcurrencyCapExceeded,
    DepthCapExceeded,
    SubAgentPool,
)
from arcen.stream.events import Spawn, SpawnDone, to_line
from arcen.tools.registry import load_builtin


@pytest.fixture()
def registry() -> object:
    return load_builtin()


@pytest.fixture()
def sink() -> list:
    return []


@pytest.fixture()
def pool(registry, sink) -> SubAgentPool:
    return SubAgentPool(registry, emit=sink.append)


def _echo_steps(n: int = 1) -> list[dict]:
    return [{"id": i + 1, "tool": "bash", "args": {"cmd": f"echo step-{i + 1}"}} for i in range(n)]


def test_spawn_returns_ok_calls_duration(pool, sink) -> None:
    # mirrors the ticket: spawn RESEARCH, wait for done → {ok, calls, duration}
    result = pool.spawn("DRAFT", "RESEARCH", "survey repo", 1, _echo_steps(2))
    assert set(result) == {"name", "ok", "calls", "duration_s"}
    assert result["ok"] is True
    assert result["calls"] == 2
    assert result["duration_s"] >= 0


def test_spawn_events_emitted_in_order(pool, sink) -> None:
    pool.spawn("DRAFT", "TEST-READER", "extract assertion", 1, _echo_steps(1))
    kinds = [e.TYPE for e in sink]
    assert kinds == ["spawn", "command", "command.done", "spawn.done"]
    spawn = sink[0]
    assert isinstance(spawn, Spawn)
    assert (spawn.parent, spawn.name, spawn.depth) == ("DRAFT", "TEST-READER", 1)
    done = sink[-1]
    assert isinstance(done, SpawnDone)
    assert (done.name, done.ok, done.calls) == ("TEST-READER", True, 1)


def test_depth_cap_enforced(pool) -> None:
    # depth 2 is allowed by default (grandchild)
    result = pool.spawn("TEST-READER", "GRANDCHILD", "help", 2, _echo_steps(1))
    assert result["ok"] is True
    # depth 3 is refused — cap is 2
    with pytest.raises(DepthCapExceeded):
        pool.spawn("GRANDCHILD", "GREAT-GRANDCHILD", "too deep", 3, _echo_steps(1))


def test_concurrency_cap_enforced(registry) -> None:
    pool = SubAgentPool(registry, max_concurrent=1)
    release = threading.Event()

    class BlockingRegistry:
        def dispatch(self, name, args):
            release.wait(timeout=5)
            return {"ok": True, "result": {"stdout": "", "exit": 0}, "error": None}

    pool.registry = BlockingRegistry()  # type: ignore[assignment]
    container: dict = {}

    def worker():
        container["first"] = pool.spawn("DRAFT", "SLOW", "holds the slot", 1, _echo_steps(1))

    t = threading.Thread(target=worker)
    t.start()
    try:
        with pytest.raises(ConcurrencyCapExceeded):
            pool.spawn("DRAFT", "SECOND", "should be refused", 1, _echo_steps(1))
    finally:
        release.set()
        t.join(timeout=5)
    assert container["first"]["ok"] is True


def test_depth_cap_zero_refuses_all(pool) -> None:
    pool.max_depth = 0
    with pytest.raises(DepthCapExceeded):
        pool.spawn("DRAFT", "ANY", "no subs allowed", 1, _echo_steps(1))


def test_failed_step_marks_done_not_ok(pool, sink) -> None:
    steps = [{"id": 1, "tool": "bash", "args": {"cmd": "exit 3"}}]
    result = pool.spawn("DRAFT", "DOOMED", "will fail", 1, steps)
    assert result["ok"] is False
    assert result["calls"] == 1
    done = sink[-1]
    assert isinstance(done, SpawnDone)
    assert done.ok is False


def test_events_serialize_frozen_schema(pool, sink) -> None:
    pool.spawn("DRAFT", "SERIALIZE", "check the wire", 1, _echo_steps(1))
    for e in sink:
        if e.TYPE in {"spawn", "spawn.done"}:
            assert '"type":"' in to_line(e)


def test_teardown_releases_slot(registry) -> None:
    pool = SubAgentPool(registry, max_concurrent=1)
    pool.spawn("DRAFT", "ONE", "first", 1, _echo_steps(1))
    pool.spawn("DRAFT", "TWO", "second", 1, _echo_steps(1))  # slot was released
    assert len(pool.spawned) == 2
