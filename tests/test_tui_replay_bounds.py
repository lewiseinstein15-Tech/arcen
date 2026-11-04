"""Bounded session replay, not global HTTP or TUI resource limits."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from arcen.tui import client as module
from arcen.tui.client import ArcenAPIError, ArcenClient, ArcenReplayProtocolError


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False
        self.read = False

    async def __aiter__(self):
        self.read = True
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        self.closed = True


async def request(chunks, *, status=200, headers=None):
    source = Chunks(chunks)
    seen = []

    async def handler(req):
        seen.append(req)
        return httpx.Response(status, stream=source, headers=headers)

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    ) as http:
        try:
            result = await ArcenClient(http=http).session_events("fixture")
            return result, source, seen
        finally:
            assert source.closed


async def test_fragmented_utf8_replay_requests_identity_and_returns_full_list():
    events = [{"seq": 1, "type": "think", "text": "café"}, {"seq": 2, "type": "run.done"}]
    body = json.dumps(events, ensure_ascii=False).encode()
    result, source, requests = await request([body[i : i + 1] for i in range(len(body))])
    assert result == events
    assert source.read
    assert requests[0].headers["accept-encoding"] == "identity"
    assert requests[0].url.path == "/api/sessions/fixture/events"


async def test_empty_array_is_valid():
    assert (await request([b"[]"]))[0] == []


@pytest.mark.parametrize(
    "payload",
    [
        b'{"seq":1}',
        b'[{"seq":1,"seq":2}]',
        b'[{"seq":1,"payload":{"x":1,"x":2}}]',
        b'[{"x":"\xff"}]',
        b'[{"seq":NaN}]',
        b'[{"seq":Infinity}]',
        b"[" * 10000 + b"]" * 10000,
        b'[{"seq":1},',
    ],
)
async def test_invalid_replay_never_returns_partial_events(payload):
    with pytest.raises(ArcenReplayProtocolError):
        await request([payload])


@pytest.mark.parametrize("encoding", ["gzip", "br", "identity, gzip"])
async def test_compressed_replay_refused_before_reading(encoding):
    source = Chunks([b"not a gzip body"])

    async def handler(req):
        return httpx.Response(200, headers={"content-encoding": encoding}, stream=source)

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    ) as http:
        with pytest.raises(ArcenReplayProtocolError, match="encoded"):
            await ArcenClient(http=http).session_events("fixture")
    assert source.closed and not source.read


@pytest.mark.parametrize("chunks", [[b"[", b" ", b" ", b" ", b"]"], [b"[   ]"]])
async def test_oversize_single_or_fragmented_body_fails(monkeypatch, chunks):
    monkeypatch.setattr(module, "MAX_REPLAY_BYTES", 4)
    with pytest.raises(ArcenReplayProtocolError, match="byte limit"):
        await request(chunks)


async def test_exact_byte_and_event_limits_are_accepted(monkeypatch):
    body = b"[{},{}]"
    monkeypatch.setattr(module, "MAX_REPLAY_BYTES", len(body))
    monkeypatch.setattr(module, "MAX_REPLAY_EVENTS", 2)
    assert (await request([body]))[0] == [{}, {}]
    monkeypatch.setattr(module, "MAX_REPLAY_EVENTS", 1)
    with pytest.raises(ArcenReplayProtocolError, match="event limit"):
        await request([body])


async def test_actual_eight_mib_boundary():
    body = b"[" + b" " * (module.MAX_REPLAY_BYTES - 2) + b"]"
    assert (await request([body[:500000], body[500000:]]))[0] == []
    with pytest.raises(ArcenReplayProtocolError, match="byte limit"):
        await request([body + b" "])


async def test_http_error_does_not_consume_error_body():
    source = Chunks([b"x" * 100])

    async def handler(req):
        return httpx.Response(503, stream=source)

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    ) as http:
        with pytest.raises(ArcenAPIError) as error:
            await ArcenClient(http=http).session_events("fixture")
    assert error.value.status == 503
    assert source.closed and not source.read


async def test_invalid_boot_replay_halts_without_attaching_live_stream():
    pytest.importorskip("textual")
    from arcen.tui.live import LiveApp

    paths = []

    async def handler(req):
        paths.append(req.url.path)
        if req.url.path.endswith("/events"):
            return httpx.Response(200, stream=Chunks([b'[{"seq":1,"seq":2,"type":"run.done"}]']))
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    ) as http:
        app = LiveApp(client=ArcenClient(http=http), session_id="fixture")
        async with app.run_test(size=(100, 30)):
            await asyncio.wait_for(app._reader_task, timeout=3)
            assert paths == ["/api/sessions/fixture/events"]
            assert app.adapter.state.last_seq == 0
            assert not app.online and app._stream_halted
            assert app.header.quarantine == "replay halted · blocked"
            assert not app.footer.live
            assert "session replay halted" in app._connection_message


async def test_failed_manual_replay_preserves_existing_session():
    pytest.importorskip("textual")
    from arcen.tui.live import LiveApp

    async def handler(req):
        if req.url.path.endswith("/events"):
            return httpx.Response(200, stream=Chunks([b'[{"seq":1,"seq":2}]']))
        if req.url.path == "/api/health":
            return httpx.Response(503)
        return httpx.Response(404)

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    ) as http:
        app = LiveApp(client=ArcenClient(http=http), retry_seconds=30)
        async with app.run_test(size=(100, 30)):
            original = app.session_id
            await app._open_session("other")
            assert app.session_id == original
            assert "session replay unavailable" in app._connection_message
