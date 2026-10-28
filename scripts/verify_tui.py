#!/usr/bin/env python3
"""Headless verification + SVG screenshots for the ARCEN TUI.

Runs the full Textual app under the pilot harness with a scripted in-memory
client (no server, no sockets), drives one complete narrated turn through
the composer, and writes SVG screenshots into docs/:

  docs/tui-screenshot.svg          — the live event transcript
  docs/tui-screenshot-config.svg   — the config + sandbox modal

Exits non-zero on any failed expectation. Run:  python scripts/verify_tui.py
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from arcen.tui._legacy.app import ArcenTUI
from arcen.tui.client import new_session_id
from arcen.tui._legacy.widgets import ConfigScreen

DOCS = pathlib.Path(__file__).resolve().parents[1] / "docs"

SCRIPTED_TURN = [
    {"seq": 1, "type": "run.start", "run_id": "r-7f3a9c",
     "goal": "fix the failing test in tests/test_pay.py", "depth": 0, "ts": 1000.0},
    {"seq": 2, "type": "think", "agent": "DRAFT",
     "text": "Read the failing test first, then the module under test.", "ts": 1000.1},
    {"seq": 3, "type": "plan", "agent": "DRAFT", "steps": [
        {"id": 1, "title": "read failing test", "tool": "file.read"},
        {"id": 2, "title": "run pytest -q", "tool": "bash"},
        {"id": 3, "title": "apply minimal fix", "tool": "file.edit"}], "ts": 1000.2},
    {"seq": 4, "type": "spawn", "parent": "DRAFT", "name": "TEST-READER",
     "task": "extract the failing assertion", "depth": 1, "ts": 1000.3},
    {"seq": 5, "type": "spawn.done", "name": "TEST-READER", "ok": True,
     "calls": 2, "duration_s": 0.41, "ts": 1000.7},
    {"seq": 6, "type": "command", "agent": "FORGE", "step": 1, "tool": "bash",
     "args": {"cmd": "pytest -q tests/test_pay.py"}, "ts": 1001.0},
    {"seq": 7, "type": "command.done", "step": 1, "ok": False,
     "result": {"error": "assert 4 == 5 failed"}, "duration_s": 0.82, "ts": 1001.8},
    {"seq": 8, "type": "step.fail", "step": 1,
     "reason": "test expects 5, calc(2,2) returns 4 — test bug", "retry": 0, "ts": 1001.9},
    {"seq": 9, "type": "plan.update", "agent": "DRAFT",
     "reason": "test bug found; fix the assertion", "steps": [
        {"id": 1, "title": "edit test to expect 4", "tool": "file.edit"},
        {"id": 2, "title": "re-run suite", "tool": "bash"}], "ts": 1002.0},
    {"seq": 10, "type": "command", "agent": "FORGE", "step": 1, "tool": "file.edit",
     "args": {"path": "tests/test_pay.py", "find": "== 5", "replace": "== 4"},
     "ts": 1002.2},
    {"seq": 11, "type": "file.diff", "path": "tests/test_pay.py",
     "patch": "--- a/tests/test_pay.py\n+++ b/tests/test_pay.py\n@@\n-assert calc(2, 2) == 5\n+assert calc(2, 2) == 4", "ts": 1002.25},
    {"seq": 12, "type": "command.done", "step": 1, "ok": True,
     "result": {"path": "tests/test_pay.py", "bytes_changed": 9},
     "duration_s": 0.03, "ts": 1002.3},
    {"seq": 13, "type": "verify.start", "agent": "TEMPER", "target": "tests/", "ts": 1002.5},
    {"seq": 14, "type": "step.pass", "step": 2,
     "checks": ["pytest -q tests/  # 12 passed"], "ts": 1004.1},
    {"seq": 15, "type": "answer",
     "text": "The test expected calc(2, 2) == 5; calc correctly returns 4. "
             "Fixed the assertion. Suite: 12 passed.", "ts": 1004.4},
    {"seq": 16, "type": "memory", "op": "write", "entity": "test_pay",
     "fact": "turn r-7f3a9c: 4 steps, verified=True", "ts": 1004.5},
    {"seq": 17, "type": "usage", "tokens": {"input": 18432, "output": 1204},
     "cost_usd": 0.021, "ts": 1004.51},
    {"seq": 18, "type": "run.done", "status": "ok", "steps": 4,
     "duration_s": 4.52, "ts": 1004.52},
]


class ScriptedClient:
    """Deterministic ArcenClient stand-in for the verification run."""

    def __init__(self, session: str) -> None:
        self.base_url = "http://127.0.0.1:3002"
        self.session = session
        self.submitted: list[str] = []

    async def aclose(self) -> None: ...
    async def health(self) -> bool:
        return True

    async def sandbox_status(self) -> dict:
        return {"backend": "auto", "effective": "process", "degraded": True,
                "docker_available": False, "image_present": False,
                "image": "ghcr.io/lewiseinstein15-tech/arcen-sandbox:0.1.0",
                "reason": "no docker daemon — degraded to the quarantined process backend"}

    async def list_sessions(self) -> list[dict]:
        return [{"id": self.session, "title": "fix the failing test", "events": 18}]

    async def session_events(self, sid: str) -> list[dict]:
        return list(SCRIPTED_TURN)

    async def get_config(self) -> dict:
        return {"provider": {"name": "custom",
                             "base_url": "https://inference.example/v1",
                             "api_key": "<redacted>", "model": "deepseek-v4"},
                "agents": {"draft": {"model": None}, "forge": {"model": None},
                           "temper": {"model": None}},
                "sandbox": {"backend": "auto"}, "mcps": [],
                "plugins": {"enabled": ["redact-secrets"]}}

    async def submit_run(self, goal: str, session: str) -> dict:
        self.submitted.append(goal)
        return {"run_id": "r-7f3a9c", "session": session}

    async def interrupt(self, run_id: str) -> dict:
        return {"ok": True, "run_id": run_id, "interrupted": True}

    async def stream(self, session: str, last_event_id=None):
        for event in SCRIPTED_TURN:
            yield event


async def main() -> int:
    DOCS.mkdir(exist_ok=True)
    sid = new_session_id()
    client = ScriptedClient(sid)
    app = ArcenTUI(client=client, session_id=sid)
    seen: list[dict] = []

    async with app.run_test(size=(128, 42)) as pilot:
        # wait for the health worker to flip online
        for _ in range(100):
            await pilot.pause()
            if app.online:
                break
        assert app.online, "health worker never went online"

        original = app.event_log.write_event
        app.event_log.write_event = lambda e: (seen.append(e), original(e))  # type: ignore[method-assign]

        app.composer.value = "fix the failing test in tests/test_pay.py"
        await pilot.press("enter")
        for _ in range(100):
            await pilot.pause()
            if not app.busy:
                break
        assert not app.busy, "turn never finished"
        assert client.submitted, "POST /api/run was never issued"
        assert seen[0]["type"] == "run.start"
        assert seen[-1]["type"] == "run.done"
        assert app.last_seq == 18, f"resume cursor wrong: {app.last_seq}"

        main_svg = DOCS / "tui-screenshot.svg"
        app.save_screenshot(filename=main_svg.name, path=str(DOCS))
        assert main_svg.exists() and main_svg.stat().st_size > 1000

        # second screenshot: the config + sandbox modal
        app.push_screen(ConfigScreen(client))
        for _ in range(20):
            await pilot.pause()
        config_svg = DOCS / "tui-screenshot-config.svg"
        app.save_screenshot(filename=config_svg.name, path=str(DOCS))
        assert config_svg.exists()

    print(f"OK  {len(seen)} events rendered")
    print(f"OK  {main_svg.relative_to(DOCS.parent)}")
    print(f"OK  {config_svg.relative_to(DOCS.parent)}")
    print("TUI verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
