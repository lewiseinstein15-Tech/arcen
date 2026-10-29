"""TUI-11: stream → adapter integration with real NDJSON framing."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

pytest.importorskip("textual")

from arcen.tui.client import ArcenClient
from arcen.tui.live import LiveApp

FIXTURE = Path(__file__).parent / "fixtures/tui/server-replan.jsonl"


def events():
    return [json.loads(line) for line in FIXTURE.read_text().splitlines()]


def lines(items):
    return "".join(json.dumps(item) + "\n" for item in items)


async def test_reconnects_after_eof_with_last_event_id_and_exact_replay():
    wire = events()
    calls = []
    async def handler(req):
        if req.url.path == "/api/health":
            return httpx.Response(200, json={"ok": True})
        if req.url.path == "/api/stream":
            calls.append(req.headers.get("last-event-id"))
            if len(calls) == 1:
                return httpx.Response(200, text=lines(wire[:4]))
            return httpx.Response(200, text=lines(wire[4:] + [{"type": "stream.done"}]))
        return httpx.Response(404)
    http = httpx.AsyncClient(base_url="http://mock", transport=httpx.MockTransport(handler))
    client = ArcenClient("http://mock", http=http)
    app = LiveApp(client=client, retry_seconds=0.01)
    try:
        async with app.run_test(size=(132, 44)) as pilot:
            await asyncio.wait_for(app._reader_task, timeout=3)
            await pilot.pause()
            assert calls == [None, "4"]
            assert app.adapter.state.last_seq == 17
            assert app.adapter.state.status == "ok"
            assert app.header.phase == "DONE"
            assert [c.kind for c in app.adapter.state.cards].count("answer") == 1
            assert any("reconnecting" in str(getattr(x, "plain", "")) for x in app.narration.items)
    finally:
        await http.aclose()


async def test_gap_notice_and_unknown_extension_do_not_crash():
    async def handler(req):
        if req.url.path == "/api/health": return httpx.Response(200, json={"ok": True})
        if req.url.path == "/api/stream":
            data = [{"seq": 1, "type": "run.start", "run_id": "r", "goal": "test"},
                    {"seq": 3, "type": "harness.new"},
                    {"seq": 4, "type": "run.done", "status": "ok"},
                    {"type": "stream.done"}]
            return httpx.Response(200, text=lines(data))
        return httpx.Response(404)
    http = httpx.AsyncClient(base_url="http://mock", transport=httpx.MockTransport(handler))
    app = LiveApp(client=ArcenClient("http://mock", http=http), retry_seconds=0.01)
    try:
        async with app.run_test(size=(100, 30)):
            await asyncio.wait_for(app._reader_task, timeout=3)
            assert any("event gap: expected 2, received 3" in str(getattr(x, "plain", ""))
                       for x in app.narration.items)
            assert app.adapter.state.last_seq == 4
    finally:
        await http.aclose()


async def test_session_replay_occurs_before_held_stream():
    wire = events()
    order = []
    async def handler(req):
        order.append(req.url.path)
        if req.url.path.endswith("/events"): return httpx.Response(200, json=wire)
        if req.url.path == "/api/health": return httpx.Response(200, json={"ok": True})
        if req.url.path == "/api/stream":
            assert req.headers.get("last-event-id") == "17"
            return httpx.Response(200, text=lines([{"seq":18,"type":"run.done","status":"ok"},{"type":"stream.done"}]))
        return httpx.Response(404)
    http = httpx.AsyncClient(base_url="http://mock", transport=httpx.MockTransport(handler))
    app = LiveApp(client=ArcenClient("http://mock", http=http), session_id="fixture", retry_seconds=.01)
    try:
        async with app.run_test(size=(100, 30)):
            await asyncio.wait_for(app._reader_task, timeout=3)
            assert order.index("/api/sessions/fixture/events") < order.index("/api/stream")
            assert len([c for c in app.adapter.state.cards if c.kind == "answer"]) == 1
    finally:
        await http.aclose()


async def test_offline_is_visible_and_recovers():
    attempts = 0
    async def handler(req):
        nonlocal attempts
        if req.url.path == "/api/health":
            attempts += 1
            return httpx.Response(503) if attempts == 1 else httpx.Response(200, json={"ok":True})
        if req.url.path == "/api/stream":
            return httpx.Response(200, text=lines([{"seq":1,"type":"run.done","status":"ok"},{"type":"stream.done"}]))
        return httpx.Response(404)
    http = httpx.AsyncClient(base_url="http://mock", transport=httpx.MockTransport(handler))
    app = LiveApp(client=ArcenClient("http://mock", http=http), retry_seconds=.01)
    try:
        async with app.run_test():
            await asyncio.wait_for(app._reader_task, timeout=3)
            assert attempts >= 2 and app.online
            assert any("offline" in str(getattr(x, "plain", "")) for x in app.narration.items)
    finally:
        await http.aclose()


async def test_degraded_sandbox_is_visible_and_rail_is_honest():
    async def handler(req):
        if req.url.path == "/api/health": return httpx.Response(200, json={"ok": True})
        if req.url.path == "/api/sandbox/status":
            return httpx.Response(200, json={"effective": "process", "degraded": True, "reason": "no docker"})
        if req.url.path == "/api/stream":
            return httpx.Response(200, text=lines([{"seq": 1, "type": "run.done", "status": "ok"}, {"type": "stream.done"}]))
        return httpx.Response(404)
    http = httpx.AsyncClient(base_url="http://mock", transport=httpx.MockTransport(handler))
    app = LiveApp(client=ArcenClient("http://mock", http=http), retry_seconds=.01)
    try:
        async with app.run_test():
            await asyncio.wait_for(app._reader_task, timeout=3)
            assert app.header.quarantine == "process · degraded"
            assert app.rail.state.sandbox == "process"
            assert any("sandbox degraded: no docker" in str(getattr(x, "plain", "")) for x in app.narration.items)
    finally:
        await http.aclose()
