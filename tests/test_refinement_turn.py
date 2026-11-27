"""End-to-end: a failed verification buys exactly one evidence-guided retry.

The unit tests in test_reasoning_loop.py pin the loop's contract. This one
pins the wiring: a real turn against the real server, where TEMPER fails the
suite on the first attempt and passes on the second. The turn must (a) run a
second attempt at all, (b) report it on the frozen stream, and (c) end "ok"
only because the second verification actually passed.
"""

from __future__ import annotations

import json
import threading
import time
import uuid

import httpx
import pytest
import uvicorn

from arcen.config import ArcenConfig
from arcen.llm.client import LLMResponse
from arcen.server.app import ServerState, app

PORT = 3189
BASE = f"http://127.0.0.1:{PORT}"


class _PlanLLM:
    """Minimal provider: classifies CODE, returns a two-step bash plan."""

    def is_available(self) -> bool:
        return True

    def model_for(self, role: str) -> str:
        return "stub"

    def complete(self, role, messages, **kwargs):
        content = messages[-1]["content"]
        if "Return ONLY the word" in content:
            return LLMResponse(text="CODE", model="stub", tokens={"input": 1, "output": 1})
        plan = json.dumps(
            [
                {"title": "write", "tool": "bash", "args": {"cmd": "echo written"}},
                {"title": "check", "tool": "bash", "args": {"cmd": "true"}},
            ]
        )
        return LLMResponse(text=plan, model="stub", tokens={"input": 8, "output": 8})


class _FlakySuiteRegistry:
    """Discovery always works; the suite fails once, then passes."""

    supports_host_diff = False

    def __init__(self, *, failures: int = 1) -> None:
        self.failures_left = failures
        self.pytest_calls = 0
        self.work_calls = 0

    def dispatch(self, name, args):
        cmd = args.get("cmd", "")
        if cmd.startswith("python -I -c "):
            return {
                "ok": True,
                "error": None,
                "result": {"stdout": '{"command": "python -m pytest -q"}\n', "stderr": "", "exit": 0},
            }
        if cmd == "python -m pytest -q":
            self.pytest_calls += 1
            if self.failures_left > 0:
                self.failures_left -= 1
                return {
                    "ok": False,
                    "error": "pytest exited 1",
                    "result": {"stdout": "1 failed\n", "stderr": "", "exit": 1},
                }
            return {"ok": True, "error": None, "result": {"stdout": "2 passed\n", "stderr": "", "exit": 0}}
        self.work_calls += 1
        return {"ok": True, "error": None, "result": {"stdout": "ok\n", "stderr": "", "exit": 0}}

    def close(self, *, strict=False):
        pass


@pytest.fixture()
def make_server(tmp_path, monkeypatch):
    started: list[uvicorn.Server] = []

    def _start(
        registry,
        *,
        reasoning_passes: int = 3,
        temper_reruns: int = 0,
        checkpoints_dir=None,
        memory_db=None,
    ):
        config = ArcenConfig()
        config.memory.db = str(memory_db or (tmp_path / "memory.db"))
        config.session.dir = str(tmp_path / "sessions")
        config.reasoning.max_passes = reasoning_passes
        config.agents.temper.reruns = temper_reruns
        state = ServerState(config=config)
        if checkpoints_dir is not None:
            from arcen.reasoning import CheckpointStore

            state.checkpoints = CheckpointStore(checkpoints_dir)
        state.config_path = tmp_path / "config.yaml"
        state.llm = _PlanLLM()
        monkeypatch.setattr("arcen.server.app.STATE", state)
        monkeypatch.setattr("arcen.server.app.create_turn_registry", lambda cfg: registry)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.time() + 15
        while time.time() < deadline and not server.started:
            time.sleep(0.05)
        assert server.started, "uvicorn did not start"
        started.append(server)
        return server

    yield _start
    for server in started:
        server.should_exit = True
    deadline = time.time() + 10
    while time.time() < deadline and any(server.started for server in started):
        time.sleep(0.05)


def _run_turn(client: httpx.Client, goal: str) -> list[dict]:
    session = str(uuid.uuid4())
    resp = client.post("/api/run", json={"goal": goal, "session": session})
    assert resp.status_code == 200, resp.text
    events: list[dict] = []
    with client.stream("GET", f"/api/stream?session={session}") as stream:
        for line in stream.iter_lines():
            if not line.strip():
                continue
            event = json.loads(line)
            events.append(event)
            if event["type"] in {"run.done", "run.error"}:
                break
    return events


def test_failed_suite_triggers_exactly_one_refinement(make_server) -> None:
    registry = _FlakySuiteRegistry(failures=1)
    make_server(registry)
    goal = "fix the failing test in calc.py and verify with pytest"

    with httpx.Client(base_url=BASE, timeout=60.0) as client:
        events = _run_turn(client, goal)

    kinds = [e["type"] for e in events]
    assert kinds[0] == "run.start" and kinds[-1] == "run.done"
    # two verification rounds: one failed, one passed
    assert registry.pytest_calls == 2
    assert len([e for e in events if e["type"] == "step.fail"]) == 1
    assert any(e["type"] == "step.pass" for e in events)
    # the refinement is narrated, not hidden
    thinks = [e["text"] for e in events if e["type"] == "think"]
    assert any("Refined over 2 passes" in text for text in thinks), thinks
    assert events[-1]["status"] == "ok"


def test_a_suite_that_keeps_failing_is_not_refined_forever(make_server) -> None:
    registry = _FlakySuiteRegistry(failures=99)
    make_server(registry, reasoning_passes=3)
    goal = "fix the failing regression in calc.py and verify with pytest"

    with httpx.Client(base_url=BASE, timeout=60.0) as client:
        events = _run_turn(client, goal)

    # budget = 2 refinements → at most 3 verification rounds, then stop.
    assert registry.pytest_calls <= 3
    assert events[-1]["type"] == "run.done"


def test_a_simple_goal_spends_no_refinement(make_server) -> None:
    registry = _FlakySuiteRegistry(failures=99)
    make_server(registry)
    goal = "echo hello"

    with httpx.Client(base_url=BASE, timeout=60.0) as client:
        events = _run_turn(client, goal)

    thinks = [e["text"] for e in events if e["type"] == "think"]
    assert not any("Complexity" in text for text in thinks), thinks
    assert registry.pytest_calls <= 1


def test_checkpoints_record_every_pass(make_server, tmp_path) -> None:
    from arcen.reasoning import CheckpointStore

    checkpoints = tmp_path / "checkpoints"
    registry = _FlakySuiteRegistry(failures=1)
    make_server(registry, checkpoints_dir=checkpoints)

    goal = "refactor the repository architecture and fix the failing test in calc.py"

    with httpx.Client(base_url=BASE, timeout=60.0) as client:
        events = _run_turn(client, goal)

    run_id = next(e["run_id"] for e in events if e["type"] == "run.start")
    records = CheckpointStore(checkpoints).read_run(run_id)
    assert records, "no checkpoint was written"
    assert [r["pass_index"] for r in records] == sorted(r["pass_index"] for r in records)
    assert all(r["action"] in {"preserve", "modify", "replace", "request_info"} for r in records)


def test_memory_written_by_one_turn_is_recalled_by_the_next(make_server, tmp_path) -> None:
    """The write event must be a real write, and recall must find it.

    A turn used to emit `memory op=write` and persist nothing, so the next
    turn's recall could never fire. This drives two related turns through
    the real server and asserts the second one recalls the first.
    """
    registry = _FlakySuiteRegistry(failures=0)
    make_server(registry, memory_db=tmp_path / "memory.db")

    with httpx.Client(base_url=BASE, timeout=60.0) as client:
        _run_turn(client, "create calc.py with an add() function, then run pytest")
        events = _run_turn(client, "extend calc.py add() to accept negative numbers, then run pytest")

    recalls = [e for e in events if e["type"] == "memory" and e["op"] == "recall"]
    assert recalls, [e for e in events if e["type"] == "memory"]
    assert "calc.py" in recalls[0]["fact"].lower() or "related" in recalls[0]["fact"].lower()
