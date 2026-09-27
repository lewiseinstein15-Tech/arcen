"""T-009 / Test-plan T-08 — FORGE executor (BACKEND-SPEC Part 1).

Proves: executes exactly one step per call; emits command + command.done;
routes through the registry; file.diff on real mutations.
"""

import pytest

from arcen.agents.forge import IDLE, ERROR, ForgeExecutor
from arcen.stream.events import Command, CommandDone, FileDiff, to_line
from arcen.tools.registry import load_builtin


@pytest.fixture()
def registry() -> object:
    return load_builtin()


@pytest.fixture()
def forge(registry) -> ForgeExecutor:
    return ForgeExecutor(registry)


def test_one_step_per_call_emits_command_and_done(forge) -> None:
    events = forge.execute_step({"id": 1, "tool": "bash", "args": {"cmd": "echo hi"}})
    assert [type(e) for e in events] == [Command, CommandDone]
    cmd, done = events
    assert cmd.agent == "FORGE" and cmd.tool == "bash" and cmd.args == {"cmd": "echo hi"}
    assert done.step == 1
    assert done.ok is True
    assert done.result == {"stdout": "hi\n", "stderr": "", "exit": 0}
    assert done.duration_s >= 0


def test_state_machine_returns_to_idle(forge) -> None:
    assert forge.state == IDLE
    forge.execute_step({"id": 1, "tool": "bash", "args": {"cmd": "true"}})
    assert forge.state == IDLE
    forge.execute_step({"id": 2, "tool": "bash", "args": {"cmd": "exit 1"}})
    assert forge.state == ERROR  # failed step is visible in state
    forge.execute_step({"id": 3, "tool": "bash", "args": {"cmd": "true"}})
    assert forge.state == IDLE


def test_no_batching_running_step_guard(forge) -> None:
    # step-at-a-time is the contract: a second call while running is refused
    original = forge.registry.dispatch

    def slow_dispatch(name, args):
        assert forge.state == "running"
        return original(name, args)

    forge.registry.dispatch = slow_dispatch
    forge.execute_step({"id": 1, "tool": "bash", "args": {"cmd": "true"}})
    with pytest.raises(RuntimeError, match="step-at-a-time"):
        # simulate a re-entrant call by pinning state
        forge.state = "running"
        forge.execute_step({"id": 2, "tool": "bash", "args": {"cmd": "true"}})


def test_routes_through_registry_unknown_tool(forge) -> None:
    events = forge.execute_step({"id": 5, "tool": "no.such.tool", "args": {}})
    cmd, done = events
    assert isinstance(cmd, Command)
    assert done.ok is False
    assert "unknown tool" in done.result["error"]


def test_file_diff_emitted_on_mutation(forge, tmp_path) -> None:
    p = tmp_path / "f.txt"
    p.write_text("before\n")
    events = forge.execute_step(
        {"id": 2, "tool": "file.write", "args": {"path": str(p), "content": "after\n"}}
    )
    assert [type(e) for e in events] == [Command, CommandDone, FileDiff]
    diff = events[2]
    assert diff.path == str(p)
    assert "-before" in diff.patch and "+after" in diff.patch


def test_no_diff_when_content_unchanged(forge, tmp_path) -> None:
    p = tmp_path / "same.txt"
    p.write_text("same\n")
    events = forge.execute_step(
        {"id": 3, "tool": "file.write", "args": {"path": str(p), "content": "same\n"}}
    )
    assert len(events) == 2  # command + command.done only


def test_events_serialize_frozen_schema(forge) -> None:
    for event in forge.execute_step({"id": 9, "tool": "bash", "args": {"cmd": "true"}}):
        line = to_line(event)
        assert '"type":"' in line


def test_main_demo(capsys) -> None:
    from arcen.agents.forge import main

    rc = main([])
    out = capsys.readouterr().out.strip().splitlines()
    assert rc == 0
    assert '"type":"command"' in out[0]
    assert '"type":"command.done"' in out[1]
    assert "forge-online" in out[1]
