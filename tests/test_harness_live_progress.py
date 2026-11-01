"""Opt-in live TUI reading untrusted metadata from a simulated HTTP server."""

from __future__ import annotations

import asyncio
import json
from io import StringIO

import httpx
import pytest

pytest.importorskip("textual")

from rich.console import Console

from arcen.stream.emitter import StreamEmitter
from arcen.stream.events import RunDone, RunStart
from arcen.stream.events_v2 import ProgressStream
from arcen.tui.client import ArcenClient
from arcen.tui.harness_demo import simulated_progress
from arcen.tui.live import LiveApp


def build_wire():
    emitter = StreamEmitter("fabricated")
    emitter.emit(RunStart(seq=0, run_id="fake", goal="SIMULATED fixture; no execution"))
    bridge = ProgressStream(emitter)
    for item in simulated_progress():
        bridge(item)
    emitter.emit(RunDone(seq=0, status="ok", steps=0, duration_s=0))
    return emitter.replay(0)


def lines(items):
    return "".join(json.dumps(item) + "\n" for item in items)


def rendered(items):
    output = StringIO()
    console = Console(file=output, width=120, color_system=None)
    for item in items:
        console.print(item)
    return output.getvalue()


@pytest.mark.parametrize("enabled", [False, True])
async def test_stream_is_read_only_opt_in_and_legacy_default_is_unchanged(enabled):
    wire = build_wire()
    requests = []
    calls = []

    async def handler(req):
        requests.append((req.method, req.url.path))
        if req.url.path == "/api/health":
            return httpx.Response(200, json={"ok": True})
        if req.url.path == "/api/sandbox/status":
            return httpx.Response(200, json={"effective": "docker", "degraded": False})
        if req.url.path == "/api/stream":
            calls.append(req.headers.get("last-event-id"))
            if len(calls) == 1:
                return httpx.Response(200, text=lines(wire[:5]))
            return httpx.Response(200, text=lines(wire[5:] + [{"type": "stream.done"}]))
        return httpx.Response(404)

    http = httpx.AsyncClient(base_url="http://mock", transport=httpx.MockTransport(handler))
    app = LiveApp(
        client=ArcenClient("http://mock", http=http), retry_seconds=0.01, harness_progress=enabled
    )
    try:
        async with app.run_test(size=(132, 44)):
            await asyncio.wait_for(app._reader_task, timeout=5)
            text = rendered(app.narration.items)
            assert calls == [None, "5"] and app.adapter.state.last_seq == len(wire)
            assert app.adapter.state.status == "ok"
            assert all(method == "GET" for method, _ in requests)
            if enabled:
                assert app.harness_progress_view.accepted == 9
                assert "uncalibrated" in text.lower() and "not an adoption decision" in text
                assert "This view performs no adoption" in text
            else:
                assert app.harness_progress_view is None
                assert "not an adoption decision" not in text
    finally:
        await http.aclose()


async def test_invalid_v2_metadata_does_not_render_or_create_controls():
    wire = build_wire()
    wire[1]["task"] = "PRIVATE UNTRUSTED TASK"
    wire[2]["ts"] = float("nan")
    wire[3]["type"] = "approval.request"

    async def handler(req):
        if req.url.path == "/api/health":
            return httpx.Response(200, json={"ok": True})
        if req.url.path == "/api/stream":
            return httpx.Response(200, text=lines(wire + [{"type": "stream.done"}]))
        return httpx.Response(404)

    http = httpx.AsyncClient(base_url="http://mock", transport=httpx.MockTransport(handler))
    app = LiveApp(
        client=ArcenClient("http://mock", http=http), retry_seconds=0.01, harness_progress=True
    )
    try:
        async with app.run_test(size=(100, 30)):
            await asyncio.wait_for(app._reader_task, timeout=5)
            text = rendered(app.narration.items)
            assert "PRIVATE UNTRUSTED TASK" not in text
            assert app.harness_progress_view.accepted == 6
            assert app.adapter.state.status == "ok"
            assert "approval.request" not in app.adapter.handlers
    finally:
        await http.aclose()


async def test_session_replacement_reinstalls_opt_in_reader_and_ignores_replay_duplicates():
    wire = build_wire()

    async def handler(req):
        if req.url.path == "/api/health":
            return httpx.Response(200, json={"ok": True})
        if req.url.path == "/api/stream":
            return httpx.Response(200, text=lines(wire + [{"type": "stream.done"}]))
        return httpx.Response(404)

    http = httpx.AsyncClient(base_url="http://mock", transport=httpx.MockTransport(handler))
    app = LiveApp(
        client=ArcenClient("http://mock", http=http), retry_seconds=0.01, harness_progress=True
    )
    try:
        async with app.run_test(size=(100, 30)):
            await asyncio.wait_for(app._reader_task, timeout=5)
            old_view = app.harness_progress_view

            async def no_stream():
                return None

            app._stream_loop = no_stream
            await app._replace_session("another-session", wire)
            await app._reader_task
            assert app.harness_progress_view is not old_view
            assert app.harness_progress_view.accepted == 9
            before = len(app.narration.items)
            assert not app._apply_event(wire[-2])
            assert len(app.narration.items) == before
    finally:
        await http.aclose()


def test_flag_reaches_live_client_without_starting_server(monkeypatch):
    from arcen.tui import live

    created = []

    class FakeApp:
        def __init__(self, **kwargs):
            created.append(kwargs)

        def run(self):
            pass

    monkeypatch.setattr("arcen.tui.launcher.ensure_server", lambda url, serve: (url, None))
    monkeypatch.setattr(live, "LiveApp", FakeApp)
    assert live.run(["--no-serve", "--harness-progress"]) == 0
    assert created[-1]["harness_progress"] is True
    assert live.run(["--no-serve"]) == 0
    assert created[-1]["harness_progress"] is False


def test_invalid_option_is_rejected_before_client_creation():
    with pytest.raises(ValueError, match="boolean"):
        LiveApp(harness_progress="yes")
