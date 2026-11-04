"""Do not buffer stream error bodies or loop on repeated compaction."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from arcen.tui.client import ArcenAPIError, ArcenClient, ArcenStreamProtocolError


class TrackingStream(httpx.AsyncByteStream):
    def __init__(self, chunks=(), *, fail=False):
        self.chunks = chunks
        self.fail = fail
        self.read = False
        self.closed = False

    async def __aiter__(self):
        self.read = True
        for chunk in self.chunks:
            yield chunk
        if self.fail:
            raise httpx.ReadError("fixture disconnect")

    async def aclose(self):
        self.closed = True


def response(status, source):
    return httpx.Response(status, stream=source, headers={"content-encoding": "gzip"})


async def test_404_body_is_not_read_before_retry():
    bad = TrackingStream([b"x" * 1_000_000])
    calls = []

    async def handler(req):
        calls.append(req)
        if len(calls) == 1:
            return response(404, bad)
        return httpx.Response(200, stream=TrackingStream([b'{"seq":1,"type":"think"}\n']))

    async with httpx.AsyncClient(
        base_url="http://fixture", transport=httpx.MockTransport(handler)
    ) as http:
        events = [e async for e in ArcenClient(http=http).stream("fixture")]
    assert [e["seq"] for e in events] == [1]
    assert len(calls) == 2 and bad.closed and not bad.read


async def test_404_retry_limit_closes_all_unread_bodies():
    bodies = []

    async def handler(req):
        body = TrackingStream([b"untrusted body"])
        bodies.append(body)
        return response(404, body)

    async with httpx.AsyncClient(
        base_url="http://fixture", transport=httpx.MockTransport(handler)
    ) as http:
        with pytest.raises(ArcenAPIError) as exc:
            _ = [e async for e in ArcenClient(http=http).stream("fixture", max_hold_retries=2)]
    assert exc.value.status == 404 and len(bodies) == 3
    assert all(b.closed and not b.read for b in bodies)


@pytest.mark.parametrize("status", [400, 401, 500, 503])
async def test_other_error_body_not_read_or_exposed(status):
    body = TrackingStream([b"private untrusted error text"])

    async def handler(req):
        return response(status, body)

    async with httpx.AsyncClient(
        base_url="http://fixture", transport=httpx.MockTransport(handler)
    ) as http:
        with pytest.raises(ArcenAPIError) as exc:
            _ = [e async for e in ArcenClient(http=http).stream("fixture")]
    assert exc.value.status == status and "private" not in str(exc.value)
    assert body.closed and not body.read


async def test_compaction_once_resets_cursor_and_does_not_read_body():
    body = TrackingStream([b"untrusted 409 body"])
    seen = []

    async def handler(req):
        seen.append(req.headers.get("last-event-id"))
        if len(seen) == 1:
            return response(409, body)
        return httpx.Response(200, stream=TrackingStream([b'{"seq":20,"type":"think"}\n']))

    async with httpx.AsyncClient(
        base_url="http://fixture", transport=httpx.MockTransport(handler)
    ) as http:
        events = [e async for e in ArcenClient(http=http).stream("fixture", 5)]
    assert seen == ["5", None] and [e["seq"] for e in events] == [20]
    assert body.closed and not body.read


async def test_no_hint_409_halts_without_retry_or_body_read():
    body = TrackingStream([b"untrusted 409 body"])
    calls = []

    async def handler(req):
        calls.append(req)
        return response(409, body)

    async with httpx.AsyncClient(
        base_url="http://fixture", transport=httpx.MockTransport(handler)
    ) as http:
        with pytest.raises(ArcenStreamProtocolError, match="compaction"):
            _ = [e async for e in ArcenClient(http=http).stream("fixture")]
    assert len(calls) == 1 and body.closed and not body.read


async def test_repeated_409_halts_after_one_restart():
    seen, bodies = [], []

    async def handler(req):
        seen.append(req.headers.get("last-event-id"))
        body = TrackingStream([b"untrusted 409 body"])
        bodies.append(body)
        return response(409, body)

    async with httpx.AsyncClient(
        base_url="http://fixture", transport=httpx.MockTransport(handler)
    ) as http:
        with pytest.raises(ArcenStreamProtocolError, match="compaction"):
            _ = [e async for e in ArcenClient(http=http).stream("fixture", 7)]
    assert seen == ["7", None] and all(b.closed and not b.read for b in bodies)


async def test_disconnect_after_compaction_does_not_restore_stale_cursor():
    seen = []

    async def handler(req):
        seen.append(req.headers.get("last-event-id"))
        if len(seen) == 1:
            return response(409, TrackingStream())
        if len(seen) == 2:
            return httpx.Response(200, stream=TrackingStream(fail=True))
        return httpx.Response(200, stream=TrackingStream([b'{"seq":10,"type":"think"}\n']))

    async with httpx.AsyncClient(
        base_url="http://fixture", transport=httpx.MockTransport(handler)
    ) as http:
        events = [e async for e in ArcenClient(http=http).stream("fixture", 7)]
    assert seen == ["7", None, None] and [e["seq"] for e in events] == [10]


async def test_live_tui_halts_on_unresolved_compaction():
    pytest.importorskip("textual")
    from arcen.tui.live import LiveApp

    seen = []

    async def handler(req):
        if req.url.path.endswith("/events"):
            return httpx.Response(200, json=[{"seq": 1, "type": "think", "text": "fixture"}])
        if req.url.path == "/api/health":
            return httpx.Response(200, json={"ok": True})
        if req.url.path == "/api/sandbox/status":
            return httpx.Response(200, json={"effective": "unavailable"})
        seen.append(req.headers.get("last-event-id"))
        return response(409, TrackingStream([b"untrusted 409 body"]))

    async with httpx.AsyncClient(
        base_url="http://fixture", transport=httpx.MockTransport(handler)
    ) as http:
        app = LiveApp(client=ArcenClient(http=http), session_id="fixture", retry_seconds=0.01)
        async with app.run_test(size=(100, 30)):
            await asyncio.wait_for(app._reader_task, timeout=3)
            await asyncio.sleep(0.1)
            assert seen == ["1", None]
            assert app.adapter.state.last_seq == 1
            assert not app.online and app._stream_halted
            assert app.header.quarantine == "stream halted · blocked"
            assert "compaction could not be resolved" in app._connection_message
