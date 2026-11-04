"""Bounded live NDJSON framing; not replay or global HTTP memory limits."""

from __future__ import annotations

import json

import httpx
import pytest

from arcen.tui import client as client_module
from arcen.tui.client import ArcenAPIError, ArcenClient


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks, *, fail=False):
        self.chunks = chunks
        self.fail = fail
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        if self.fail:
            raise httpx.ReadError("fixture interrupted")

    async def aclose(self):
        self.closed = True


async def collect(chunks, headers=None):
    source = Chunks(chunks)
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, stream=source, headers=headers)

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    ) as http:
        result = [event async for event in ArcenClient(http=http).stream("fixture")]
    return result, source, requests


async def test_fragmented_utf8_crlf_final_line_and_multiple_frames():
    first = json.dumps({"seq": 1, "type": "think", "text": "café"}, ensure_ascii=False).encode()
    second = b'{"seq":2,"type":"think"}'
    payload = first + b"\r\n" + b'{"seq":3,"type":"think","x":"\xff"}\n' + second
    events, source, requests = await collect([payload[i : i + 1] for i in range(len(payload))])
    assert [x["seq"] for x in events] == [1, 2]
    assert events[0]["text"] == "café"
    assert requests[0].headers["accept-encoding"] == "identity"
    assert source.closed


@pytest.mark.parametrize("newline", [b"", b"\n", b"\r\n"])
async def test_exact_limit_is_accepted(monkeypatch, newline):
    line = b'{"seq":1,"type":"think"}'
    # CR is part of the line: account for it when testing CRLF.
    monkeypatch.setattr(client_module, "MAX_LIVE_LINE_BYTES", len(line) + (newline == b"\r\n"))
    events, _, _ = await collect([line[:5], line[5:] + newline])
    assert [x["seq"] for x in events] == [1]


@pytest.mark.parametrize(
    "chunks",
    [
        [b'{"seq":1,"type":"think"}\n', b"x" * 33 + b'\n{"seq":2,"type":"think"}\n'],
        [b'{"seq":1,"type":"think"}\n' + b"x" * 33 + b'\n{"seq":2,"type":"think"}\n'],
        [b'{"seq":1,"type":"think"}\n', b"x" * 20, b"x" * 13],
    ],
)
async def test_oversize_fails_instead_of_advancing_past_frame(monkeypatch, chunks):
    monkeypatch.setattr(client_module, "MAX_LIVE_LINE_BYTES", 32)
    source = Chunks(chunks)

    async def handler(request):
        return httpx.Response(200, stream=source)

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    ) as http:
        events = []
        with pytest.raises(ArcenAPIError, match="exceeds byte limit"):
            async for event in ArcenClient(http=http).stream("fixture"):
                events.append(event)
    assert [x["seq"] for x in events] == [1]
    assert source.closed


@pytest.mark.parametrize("encoding", ["gzip", "br", "gzip, identity", "identity, gzip"])
async def test_encoded_stream_rejected_before_consuming_body(encoding):
    source = Chunks([b"not an encoded stream"])

    async def handler(request):
        return httpx.Response(200, stream=source, headers={"Content-Encoding": encoding})

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    ) as http:
        with pytest.raises(ArcenAPIError, match="encoded live stream"):
            _ = [x async for x in ArcenClient(http=http).stream("fixture")]
    assert source.closed


async def test_reconnect_cursor_remains_last_valid_frame_after_bad_utf8():
    requests = []

    async def handler(request):
        requests.append(request.headers.get("last-event-id"))
        if len(requests) == 1:
            return httpx.Response(
                200,
                stream=Chunks(
                    [
                        b'{"seq":1,"type":"think"}\n',
                        b'{"seq":99,"type":"think","x":"\xff"}\n',
                    ],
                    fail=True,
                ),
            )
        return httpx.Response(200, stream=Chunks([b'{"seq":2,"type":"think"}\n']))

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    ) as http:
        events = [x async for x in ArcenClient(http=http).stream("fixture")]
    assert requests == [None, "1"]
    assert [x["seq"] for x in events] == [1, 2]


async def test_actual_one_mib_boundary():
    prefix = b'{"seq":1,"type":"think","text":"'
    suffix = b'"}'
    line = prefix + b"x" * (client_module.MAX_LIVE_LINE_BYTES - len(prefix) - len(suffix)) + suffix
    events, _, _ = await collect([line[:500000], line[500000:] + b"\n"])
    assert len(events) == 1 and events[0]["seq"] == 1
    with pytest.raises(ArcenAPIError, match="exceeds byte limit"):
        await collect([line + b" \n"])


async def test_live_tui_reports_overflow_without_applying_later_event():
    import asyncio

    pytest.importorskip("textual")
    from arcen.tui.live import LiveApp

    requests = []

    async def handler(request):
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/api/sandbox/status":
            return httpx.Response(200, json={"effective": "unavailable"})
        requests.append(request)
        return httpx.Response(
            200,
            stream=Chunks(
                [
                    b'{"seq":1,"type":"think","text":"fixture"}\n',
                    b"x" * (client_module.MAX_LIVE_LINE_BYTES + 1) + b"\n",
                    b'{"seq":2,"type":"run.done","status":"ok"}\n',
                ]
            ),
        )

    async with httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    ) as http:
        app = LiveApp(client=ArcenClient(http=http), retry_seconds=0.01)
        async with app.run_test(size=(100, 30)):
            for _ in range(200):
                if "exceeds byte limit" in app._connection_message:
                    break
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.1)
            assert "stream halted" in app._connection_message
            assert "exceeds byte limit" in app._connection_message
            assert app.adapter.state.last_seq == 1
            assert len(requests) == 1
            assert app._reader_task.done()
            assert not app.online and app._stream_halted
            assert app.header.quarantine == "stream halted · blocked"
            assert not app.footer.live
