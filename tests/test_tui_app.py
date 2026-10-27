"""Headless smoke tests for the Textual app (no real terminal needed).

Skips when the optional ``tui`` extra is not installed. A FakeClient stands
in for the HTTP layer so the full turn loop — composer → held stream →
event log → run.done → composer re-enabled — runs deterministically.
"""

from __future__ import annotations

import pytest

pytest.importorskip("textual")

from rich.console import Console
from textual.widgets import ListView

from arcen.tui.app import ArcenTUI
from arcen.tui.client import new_session_id
from arcen.tui.widgets import ConfigScreen, HelpScreen


def _turn_events(session: str) -> list[dict]:
    return [
        {"seq": 1, "type": "run.start", "run_id": "r-fake", "goal": "fix it",
         "depth": 0, "ts": 1.0},
        {"seq": 2, "type": "think", "agent": "DRAFT", "text": "planning", "ts": 1.1},
        {"seq": 3, "type": "plan", "agent": "DRAFT",
         "steps": [{"id": 1, "title": "run tests", "tool": "bash"}], "ts": 1.2},
        {"seq": 4, "type": "command", "agent": "FORGE", "step": 1, "tool": "bash",
         "args": {"cmd": "pytest -q"}, "ts": 1.3},
        {"seq": 5, "type": "command.done", "step": 1, "ok": True,
         "result": {"stdout": "ok"}, "duration_s": 0.2, "ts": 1.4},
        {"seq": 6, "type": "answer", "text": "all green", "ts": 1.5},
        {"seq": 7, "type": "usage", "tokens": {"input": 10, "output": 5},
         "cost_usd": 0.01, "ts": 1.6},
        {"seq": 8, "type": "run.done", "status": "ok", "steps": 1,
         "duration_s": 0.6, "ts": 1.7},
    ]


class FakeClient:
    """Duck-typed stand-in for ArcenClient — in-memory, no sockets."""

    def __init__(self) -> None:
        self.base_url = "http://arcen.fake:3002"
        self.session = new_session_id()
        self.interrupted: list[str] = []
        self.submit_calls: list[str] = []
        self.closed = False
        self.online = True

    async def aclose(self) -> None:
        self.closed = True

    async def health(self) -> bool:
        return self.online

    async def sandbox_status(self) -> dict:
        return {"backend": "auto", "effective": "process", "degraded": True,
                "docker_available": False, "image_present": False,
                "image": "arcen-sandbox:0.1.0", "reason": "no docker daemon"}

    async def list_sessions(self) -> list[dict]:
        return [{"id": self.session, "title": "fix it", "events": 8}]

    async def session_events(self, sid: str) -> list[dict]:
        return list(_turn_events(sid))

    async def get_config(self) -> dict:
        return {"provider": {"name": "custom", "api_key": "<redacted>"},
                "sandbox": {"backend": "auto"}, "mcps": [], "plugins": {"enabled": []}}

    async def submit_run(self, goal: str, session: str) -> dict:
        self.submit_calls.append(goal)
        return {"run_id": "r-fake", "session": session}

    async def interrupt(self, run_id: str) -> dict:
        self.interrupted.append(run_id)
        return {"ok": True, "run_id": run_id, "interrupted": True}

    async def stream(self, session: str, last_event_id=None):
        for event in _turn_events(session):
            if last_event_id is not None and event["seq"] <= last_event_id:
                continue
            yield event


def _make_app(fake: FakeClient | None = None) -> tuple[FakeClient, ArcenTUI]:
    fake = fake or FakeClient()
    # share the fake's session id so sidebar "current" markers line up
    return fake, ArcenTUI(client=fake, session_id=fake.session)


async def _wait_idle(app: ArcenTUI, pilot, *, ticks: int = 60) -> None:
    for _ in range(ticks):
        await pilot.pause()
        if not app.busy:
            return
    raise AssertionError("turn never finished")


async def _wait_until(pilot, check, *, ticks: int = 100) -> None:
    """Spin the message loop until a worker-driven condition becomes true."""
    for _ in range(ticks):
        await pilot.pause()
        if check():
            return
    raise AssertionError("condition was never met")


def _spy_events(app: ArcenTUI) -> list[dict]:
    seen: list[dict] = []
    original = app.event_log.write_event
    app.event_log.write_event = lambda event: (seen.append(event), original(event))  # type: ignore[method-assign]
    return seen


async def test_mount_shows_welcome_and_online_status():
    _, app = _make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await _wait_until(pilot, lambda: app.online)
        # the welcome panel was the first thing written
        assert len(app.event_log.lines) >= 1
        status_text = app.statusbar.content.plain
        assert "online" in status_text and "process" in status_text
        # sessions sidebar got populated from the fake API, current session marked
        items = [i for i in app.sidebar.list_view.children
                 if i.id and i.id.startswith("session-")]
        assert items and items[0].id == f"session-{app.session_id}"


async def test_full_turn_streams_events_into_the_log():
    fake, app = _make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await _wait_until(pilot, lambda: app.online)
        seen = _spy_events(app)

        app.composer.value = "fix the failing test"
        await pilot.press("enter")
        await _wait_idle(app, pilot)

        types = [e["type"] for e in seen]
        assert types[0] == "run.start"
        assert types[-1] == "run.done"
        assert "answer" in types and "command.done" in types
        assert fake.submit_calls == ["fix the failing test"]
        # the turn released the composer and remembered its run id transiently
        assert app.composer.disabled is False
        assert app.busy is False
        # seq cursor advanced for a future Last-Event-ID resume
        assert app.last_seq == 8


async def test_new_chat_resets_session_and_log():
    _, app = _make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await _wait_until(pilot, lambda: app.online)
        welcome_strips = len(app.event_log.lines)
        old_session = app.session_id
        app.composer.value = "fix it"
        await pilot.press("enter")
        await _wait_idle(app, pilot)
        assert len(app.event_log.lines) > welcome_strips

        await pilot.press("ctrl+n")
        await pilot.pause()
        assert app.session_id != old_session
        assert app.last_seq is None
        # fresh transcript: back to exactly the welcome panel's strips
        assert len(app.event_log.lines) == welcome_strips


async def test_sidebar_toggle_help_and_config_screens_and_quit():
    _, app = _make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await _wait_until(pilot, lambda: app.online)

        await pilot.press("ctrl+b")
        await pilot.pause()
        assert app.sidebar.has_class("hidden")
        await pilot.press("ctrl+b")
        await pilot.pause()
        assert not app.sidebar.has_class("hidden")

        await pilot.press("ctrl+h")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, HelpScreen)

        await pilot.press("ctrl+o")
        await pilot.pause()
        assert isinstance(app.screen, ConfigScreen)
        await pilot.pause()  # let on_mount fetch config + sandbox
        console = Console(record=True, width=100)
        console.print(app.screen._body.content)
        assert "<redacted>" in console.export_text()
        await pilot.press("escape")
        await pilot.pause()

        await pilot.press("ctrl+q")
        assert app.is_running is False


async def test_open_historical_session_replays_events():
    _, app = _make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await _wait_until(pilot, lambda: app.online)
        seen = _spy_events(app)

        old = new_session_id()
        await app._open_session(old)
        await pilot.pause()
        assert app.session_id == old
        assert app.last_seq == 8
        assert [e["type"] for e in seen][-1] == "run.done"


async def test_interrupt_calls_delete_endpoint():
    fake, app = _make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await _wait_until(pilot, lambda: app.online)
        app.run_id = "r-xyz"
        app.action_interrupt()
        for _ in range(20):
            await pilot.pause()
            if fake.interrupted:
                break
        assert fake.interrupted == ["r-xyz"]


async def test_submit_while_offline_writes_error_banner():
    fake, app = _make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await _wait_until(pilot, lambda: app.online)
        fake.online = False  # health probe now reports down
        app.online = False
        app.composer.value = "fix it"
        await pilot.press("enter")
        await pilot.pause()
        # no run was ever posted — the guard stops the turn before /api/run
        assert fake.submit_calls == []
        assert app.busy is False
        assert app.composer.disabled is False


async def test_printable_typing_reaches_the_composer_not_keybindings():
    """Regression guard: global shortcuts must not steal letters from input."""
    _, app = _make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await _wait_until(pilot, lambda: app.online)
        app.composer.focus()
        await pilot.press(*"quiet new chat")  # all printable, no Ctrl modifiers
        await pilot.pause()
        assert app.composer.value == "quiet new chat"
        assert app.is_running is True  # 'q' inside text did not quit the app


async def test_list_view_widget_exists():
    _, app = _make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await _wait_until(pilot, lambda: app.online)
        assert isinstance(app.sidebar.list_view, ListView)
