"""Interrupt confirmation, race safety and terminal error presentation."""

import httpx
import pytest

pytest.importorskip("textual")

from arcen.tui.client import ArcenClient
from arcen.tui.interrupt import InterruptScreen
from arcen.tui.live import LiveApp


async def test_confirm_cancel_and_idle():
    deletes = []
    async def handler(req):
        if req.method == "DELETE":
            deletes.append(req.url.path)
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(503)
    http = httpx.AsyncClient(base_url="http://mock", transport=httpx.MockTransport(handler))
    app = LiveApp(client=ArcenClient("http://mock", http=http), retry_seconds=60)
    try:
        async with app.run_test() as pilot:
            await pilot.press("ctrl+c")
            assert not isinstance(app.screen, InterruptScreen)
            app._apply_event({"seq": 1, "type": "run.start", "run_id": "run-a", "goal": "Work"})
            await pilot.press("ctrl+c")
            assert isinstance(app.screen, InterruptScreen)
            await pilot.press("ctrl+c")
            assert not isinstance(app.screen, InterruptScreen)
            assert not deletes
            await pilot.press("ctrl+c", "y")
            await pilot.pause()
            assert deletes == ["/api/run/run-a"]
            assert app.adapter.state.status == "running"  # wait for server terminal event
            app._apply_event({"seq": 2, "type": "run.done", "status": "interrupted"})
            assert app.adapter.state.status == "interrupted"
            assert any(c.kind == "interrupted" for c in app.adapter.state.cards)
    finally:
        await http.aclose()


async def test_old_confirmation_cannot_interrupt_new_run_and_failure_is_visible():
    deletes = []
    async def handler(req):
        if req.method == "DELETE":
            deletes.append(req.url.path)
            return httpx.Response(500, json={"detail":"test failure"})
        return httpx.Response(503)
    http = httpx.AsyncClient(base_url="http://mock", transport=httpx.MockTransport(handler))
    app = LiveApp(client=ArcenClient("http://mock", http=http), retry_seconds=60)
    try:
        async with app.run_test() as pilot:
            app._apply_event({"seq":1,"type":"run.start","run_id":"old","goal":"a"})
            await pilot.press("ctrl+c")
            app._apply_event({"seq":2,"type":"run.done","status":"ok"})
            app._apply_event({"seq":3,"type":"run.start","run_id":"new","goal":"b"})
            await pilot.press("y")
            await pilot.pause()
            assert not deletes
            await pilot.press("ctrl+c", "enter")
            await pilot.pause()
            assert deletes == ["/api/run/new"]
            assert any(item.__class__.__name__ == "Table" for item in app.narration.items)
            assert app.adapter.state.status == "running"
    finally:
        await http.aclose()
