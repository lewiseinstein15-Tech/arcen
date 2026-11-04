"""Narrow malformed-envelope checks, not stream authentication or payload validation."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

pytest.importorskip("textual")

from arcen.stream.emitter import StreamEmitter
from arcen.stream.events_v2 import ProgressStream
from arcen.tui.client import ArcenClient, is_app_event
from arcen.tui.harness_demo import simulated_progress
from arcen.tui.live import LiveApp


@pytest.mark.parametrize(
    "event",
    [
        None,
        [],
        {},
        {"seq": True, "type": "think"},
        {"seq": "1", "type": "think"},
        {"seq": 1.0, "type": "think"},
        {"seq": 0, "type": "think"},
        {"seq": -1, "type": "think"},
        {"seq": 1, "type": []},
        {"seq": 1, "type": ""},
    ],
)
def test_rejects_bad_event_envelopes(event):
    assert not is_app_event(event)


class Interrupted(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'{"seq":1,"type":"think","text":"ok"}\n'
        yield b'{"seq":"oops","type":"think"}\n'
        yield b'{"seq":true,"type":"think"}\n'
        yield b'{"seq":2,"type":[]}\n'
        yield b'{"seq":88,"seq":89,"type":"think"}\n'
        yield b'{"seq":90,"type":"think","x":{"a":1,"a":2}}\n'
        raise httpx.ReadError("fixture disconnect")


async def test_bad_frames_do_not_advance_reconnect_cursor():
    requests = []

    async def handler(req):
        requests.append(req.headers.get("last-event-id"))
        if len(requests) == 1:
            return httpx.Response(200, stream=Interrupted())
        # Unterminated final line goes through the same envelope check.
        return httpx.Response(
            200, text='{"seq":2,"type":"think","text":"next"}\n{"seq":"bad","type":"think"}'
        )

    http = httpx.AsyncClient(base_url="http://fixture", transport=httpx.MockTransport(handler))
    try:
        client = ArcenClient("http://fixture", http=http)
        events = [event async for event in client.stream("session")]
        assert requests == [None, "1"]
        assert [event["seq"] for event in events] == [1, 2]
    finally:
        await http.aclose()


async def test_session_replay_drops_invalid_envelopes_and_keeps_valid_v2():
    emitter = StreamEmitter("fixture")
    ProgressStream(emitter)(simulated_progress()[0])
    good = emitter.replay(0)[0]
    replay = [
        None,
        [],
        {"seq": "999", "type": "think"},
        {"seq": 999, "type": []},
        good,
        {"seq": 2, "type": "run.done", "status": "ok"},
    ]
    received = []

    async def handler(req):
        if req.url.path.endswith("/events"):
            return httpx.Response(200, json=replay)
        if req.url.path == "/api/health":
            return httpx.Response(200, json={"ok": True})
        if req.url.path == "/api/stream":
            received.append(req.headers.get("last-event-id"))
            return httpx.Response(200, text=json.dumps({"type": "stream.done"}) + "\n")
        return httpx.Response(404)

    http = httpx.AsyncClient(base_url="http://fixture", transport=httpx.MockTransport(handler))
    app = LiveApp(
        client=ArcenClient("http://fixture", http=http),
        session_id="fixture",
        harness_progress=True,
        retry_seconds=0.01,
    )
    try:
        async with app.run_test(size=(100, 30)):
            for _ in range(100):
                if received:
                    break
                await asyncio.sleep(0.01)
            assert received and received[0] == "2"
            assert app.adapter.state.last_seq == 2
            assert app.harness_progress_view.accepted == 1
    finally:
        await http.aclose()


def test_unique_json_fields_required_in_live_ndjson():
    parse = ArcenClient._parse_line
    assert parse('{"seq":1,"type":"think","type":"usage"}') is None
    assert parse('{"seq":1,"type":"think","args":{"x":1,"x":2}}') is None
    assert parse('{"seq":1,"type":"think"}') == {"seq": 1, "type": "think"}
    assert parse("[" * 2000 + "]" * 2000) is None
