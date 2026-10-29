"""Composer keyboard interactions and real HTTP client ordering."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

pytest.importorskip("textual")

from arcen.tui.client import ArcenClient
from arcen.tui.composer import Composer
from arcen.tui.live import LiveApp


class TurnStream(httpx.AsyncByteStream):
    def __init__(self, event, index):
        self.event, self.index = event, index

    async def __aiter__(self):
        await self.event.wait()
        for item in [
            {
                "seq": self.index * 2 + 1,
                "type": "run.start",
                "run_id": f"run-{self.index}",
                "goal": "test",
            },
            {"seq": self.index * 2 + 2, "type": "run.done", "status": "ok"},
            {"type": "stream.done"},
        ]:
            yield (json.dumps(item) + "\n").encode()


async def test_multiline_submit_two_turns_and_stream_before_post():
    stream_events, calls, goals = [], [], []

    async def handler(req):
        calls.append((req.method, req.url.path))
        if req.url.path == "/api/health":
            return httpx.Response(200, json={"ok": True})
        if req.url.path == "/api/sandbox/status":
            return httpx.Response(200, json={"effective": "docker"})
        if req.url.path == "/api/stream":
            stream_events.append(asyncio.Event())
            return httpx.Response(200, stream=TurnStream(stream_events[-1], len(stream_events) - 1))
        if req.url.path == "/api/run":
            goals.append(json.loads(req.content))
            stream_events[-1].set()
            return httpx.Response(200, json={"run_id": "example"})
        return httpx.Response(404)

    http = httpx.AsyncClient(base_url="http://mock", transport=httpx.MockTransport(handler))
    app = LiveApp(client=ArcenClient("http://mock", http=http), retry_seconds=0.01)
    try:
        async with app.run_test(size=(132, 44)) as pilot:
            for _ in range(100):
                if stream_events:
                    break
                await asyncio.sleep(0.01)
            assert stream_events
            c = app.query_one(Composer)
            await pilot.press("h", "i", "ctrl+t", "b", "y", "e", "enter")
            await asyncio.wait_for(app._submit_task, 2)
            await asyncio.wait_for(app._reader_task, 2)
            assert goals[0]["goal"] == "hi\nbye"
            assert goals[0]["session"] == app.session_id
            assert c.text == "" and not app.busy
            await pilot.press("n", "e", "x", "t", "enter")
            await asyncio.wait_for(app._submit_task, 2)
            await asyncio.wait_for(app._reader_task, 2)
            assert goals[1]["goal"] == "next"
            assert [x for x in calls if x[1] in ("/api/stream", "/api/run")] == [
                ("GET", "/api/stream"),
                ("POST", "/api/run"),
                ("GET", "/api/stream"),
                ("POST", "/api/run"),
            ]
    finally:
        await http.aclose()


async def test_autocomplete_help_and_offline_draft_preserved():
    async def handler(req):
        return httpx.Response(503)

    http = httpx.AsyncClient(base_url="http://mock", transport=httpx.MockTransport(handler))
    app = LiveApp(client=ArcenClient("http://mock", http=http), retry_seconds=60)
    try:
        async with app.run_test() as pilot:
            c = app.query_one(Composer)
            await pilot.press("slash", "h", "tab")
            assert c.text == "/help"
            await pilot.press("enter")
            assert c.text == ""
            assert any(
                "Commands:" in str(getattr(item, "plain", "")) for item in app.narration.items
            )
            c.load_text("keep this draft")
            await pilot.press("enter")
            assert c.text == "keep this draft"
    finally:
        await http.aclose()


async def test_server_rejection_keeps_draft():
    async def handler(req):
        if req.url.path == "/api/health":
            return httpx.Response(200, json={"ok": True})
        if req.url.path == "/api/sandbox/status":
            return httpx.Response(200, json={})
        if req.url.path == "/api/stream":
            return httpx.Response(200, stream=TurnStream(asyncio.Event(), 0))
        if req.url.path == "/api/run":
            return httpx.Response(400, json={"detail": "provider refused"})
        return httpx.Response(404)

    http = httpx.AsyncClient(base_url="http://mock", transport=httpx.MockTransport(handler))
    app = LiveApp(client=ArcenClient("http://mock", http=http), retry_seconds=0.01)
    try:
        async with app.run_test() as pilot:
            for _ in range(100):
                if app.online and app._stream_started.is_set():
                    break
                await asyncio.sleep(0.01)
            c = app.query_one(Composer)
            c.load_text("keep me")
            await pilot.press("enter")
            await asyncio.wait_for(app._submit_task, 2)
            assert c.text == "keep me" and not app.busy
    finally:
        await http.aclose()


async def test_external_editor_round_trip(monkeypatch):
    from contextlib import nullcontext
    from pathlib import Path
    from types import SimpleNamespace

    async def handler(req):
        return httpx.Response(503)

    http = httpx.AsyncClient(base_url="http://mock", transport=httpx.MockTransport(handler))
    app = LiveApp(client=ArcenClient("http://mock", http=http), retry_seconds=60)
    seen = []

    def edit(argv, *, check):
        path = Path(argv[-1])
        assert path.read_text() == "old draft"
        seen.append(path)
        path.write_text("new\ntext")
        return SimpleNamespace(returncode=0)

    monkeypatch.setenv("EDITOR", "example-editor --wait")
    monkeypatch.setattr(app, "suspend", nullcontext)
    monkeypatch.setattr("arcen.tui.live.subprocess.run", edit)
    try:
        async with app.run_test() as pilot:
            composer = app.query_one(Composer)
            composer.load_text("old draft")
            await pilot.press("ctrl+g")
            assert composer.text == "new\ntext"
            assert seen and not seen[0].exists()
    finally:
        await http.aclose()
