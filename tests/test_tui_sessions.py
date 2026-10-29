"""Session picker, replay and guarded switching."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

pytest.importorskip("textual")
from arcen.tui.client import ArcenClient
from arcen.tui.live import LiveApp
from arcen.tui.sessions import SessionsScreen

FIXTURE = Path(__file__).parent / "fixtures/tui/server-replan.jsonl"
SID = "11111111-1111-4111-8111-111111111111"


class Hold(httpx.AsyncByteStream):
    async def __aiter__(self):
        await asyncio.Event().wait()
        yield b""


async def test_picker_replays_and_new_session_resets_without_losing_draft():
    events = [json.loads(line) for line in FIXTURE.read_text().splitlines()]

    async def handler(req):
        if req.url.path == "/api/health":
            return httpx.Response(200, json={"ok": True})
        if req.url.path == "/api/sandbox/status":
            return httpx.Response(200, json={"effective": "docker"})
        if req.url.path == "/api/sessions":
            return httpx.Response(
                200, json=[{"id": SID, "title": "Recorded fixture", "events": len(events)}]
            )
        if req.url.path == f"/api/sessions/{SID}/events":
            return httpx.Response(200, json=events)
        if req.url.path == "/api/stream":
            return httpx.Response(200, stream=Hold())
        return httpx.Response(404)

    http = httpx.AsyncClient(base_url="http://mock", transport=httpx.MockTransport(handler))
    app = LiveApp(client=ArcenClient("http://mock", http=http), retry_seconds=0.01)
    try:
        async with app.run_test(size=(132, 44)) as pilot:
            await pilot.press("ctrl+b")
            await asyncio.wait_for(app._session_task, 2)
            await pilot.pause()
            assert isinstance(app.screen, SessionsScreen)
            await pilot.press("enter")
            await pilot.pause()
            await asyncio.wait_for(app._session_task, 2)
            assert app.session_id == SID
            assert app.adapter.state.last_seq == 17
            assert app.header.phase == "DONE"
            assert len([c for c in app.adapter.state.cards if c.kind == "answer"]) == 1
            await pilot.press("ctrl+n")
            await asyncio.wait_for(app._session_task, 2)
            assert app.session_id != SID and app.adapter.state.last_seq == 0
            assert app.header.phase == "IDLE"
            assert not app.narration.items
            await pilot.press("ctrl+r")
            await asyncio.wait_for(app._session_task, 2)
            assert app.session_id == SID and app.adapter.state.last_seq == 17
    finally:
        await http.aclose()


async def test_cannot_switch_running_and_failed_fetch_keeps_session():
    async def handler(req):
        if req.url.path == "/api/health":
            return httpx.Response(200, json={"ok": True})
        if req.url.path == "/api/stream":
            return httpx.Response(200, stream=Hold())
        return httpx.Response(503, json={"detail": "not available"})

    http = httpx.AsyncClient(base_url="http://mock", transport=httpx.MockTransport(handler))
    app = LiveApp(client=ArcenClient("http://mock", http=http), retry_seconds=0.01)
    try:
        async with app.run_test() as pilot:
            original = app.session_id
            app._apply_event({"seq": 1, "type": "run.start", "run_id": "x", "goal": "test"})
            await pilot.press("ctrl+n", "ctrl+b", "ctrl+r")
            assert app.session_id == original and app._session_task is None
            app._apply_event({"seq": 2, "type": "run.done", "status": "ok"})
            await app._open_session(SID)
            assert app.session_id == original and app.adapter.state.last_seq == 2
            assert any(
                "replay unavailable" in str(getattr(x, "plain", "")) for x in app.narration.items
            )
    finally:
        await http.aclose()
