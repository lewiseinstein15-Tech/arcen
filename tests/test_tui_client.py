"""TUI API client — contract tests against httpx.MockTransport.

No socket, no server: the mock returns canned HTTP, including a stream
sliced into awkward byte chunks to prove partial-line NDJSON framing.
"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest

from arcen.tui.client import ArcenAPIError, ArcenClient, new_session_id


def _client(handler) -> ArcenClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(base_url="http://arcen.test:3002", transport=transport)
    return ArcenClient(http=http)


class _ChunkedStream(httpx.AsyncByteStream):
    """MockTransport needs an AsyncByteStream, not a bare async generator."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aiter__(self):
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        pass


def astream(raw: bytes, chunk_size: int = 7) -> _ChunkedStream:
    """A chunked async response body slicing raw into awkward small pieces."""
    chunks = [raw[i:i + chunk_size] for i in range(0, len(raw), chunk_size)]
    return _ChunkedStream(chunks)


def test_new_session_id_is_a_real_uuid():
    uuid.UUID(new_session_id())  # raises if malformed — the server guard accepts it


async def test_health_true_and_false():
    ok = _client(lambda req: httpx.Response(200, json={"ok": True}))
    assert await ok.health() is True

    bad = _client(lambda req: httpx.Response(500))
    assert await bad.health() is False

    def boom(req):
        raise httpx.ConnectError("no daemon")

    down = _client(boom)
    assert await down.health() is False


async def test_submit_run_returns_ids_and_surfaces_detail():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/run"
        body = json.loads(request.content)
        assert body["goal"] == "fix tests" and uuid.UUID(body["session"])
        return httpx.Response(200, json={"run_id": "r-1", "session": body["session"]})

    client = _client(handler)
    sid = new_session_id()
    out = await client.submit_run("fix tests", sid)
    assert out == {"run_id": "r-1", "session": sid}

    refuse = _client(lambda req: httpx.Response(
        409, json={"detail": "Sandbox backend is set to docker, but no daemon."}))
    with pytest.raises(ArcenAPIError) as exc:
        await refuse.submit_run("x", sid)
    assert exc.value.status == 409
    assert "no daemon" in str(exc.value)


async def test_stream_frames_partial_lines_and_skips_transport_frames():
    ndjson = "\n".join([
        json.dumps({"seq": 1, "type": "run.start", "run_id": "r-1", "goal": "g", "depth": 0}),
        '{"type":"stream.ping"}',  # seq-less keepalive — invisible
        json.dumps({"seq": 2, "type": "think", "agent": "DRAFT", "text": "hi"}),
        "{broken json line",  # malformed — skipped, never fatal
        json.dumps({"seq": 3, "type": "run.done", "status": "ok", "steps": 1,
                    "duration_s": 0.1}),
        '{"type":"stream.done"}',  # clean close marker
    ]) + "\n"
    # Slice into deliberately awkward 7-byte chunks, splitting every line.
    chunks = astream(ndjson.encode(), chunk_size=7)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/stream"
        return httpx.Response(200, stream=chunks,
                              headers={"content-type": "application/x-ndjson"})

    client = _client(handler)
    events = [e async for e in client.stream(new_session_id())]
    assert [e["seq"] for e in events] == [1, 2, 3]
    assert [e["type"] for e in events] == ["run.start", "think", "run.done"]


async def test_stream_retries_404_then_attaches():
    calls = {"n": 0}
    payload = (
        json.dumps({"seq": 1, "type": "run.start", "run_id": "r", "goal": "g",
                    "depth": 0}) + '\n{"type":"stream.done"}\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(404)
        return httpx.Response(200, stream=astream(payload.encode(), chunk_size=3))

    client = _client(handler)
    events = [e async for e in client.stream(new_session_id())]
    assert calls["n"] == 2 and len(events) == 1


async def test_stream_409_compaction_restarts_without_resume_header():
    seen_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(request.headers.get("last-event-id"))
        if len(seen_headers) == 1:
            return httpx.Response(409, json={"error": "compacted", "oldest": 50})
        line = json.dumps({"seq": 50, "type": "run.start", "run_id": "r",
                           "goal": "g", "depth": 0}) + '\n{"type":"stream.done"}\n'
        return httpx.Response(200, stream=astream(line.encode(), chunk_size=3))

    client = _client(handler)
    events = [e async for e in client.stream(new_session_id(), last_event_id=10)]
    assert seen_headers == ["10", None]  # resume hint dropped after compaction
    assert events and events[0]["seq"] == 50


class _FailingStream(httpx.AsyncByteStream):
    """Yields its chunks, then raises mid-stream like a reset connection."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aiter__(self):
        for chunk in self._chunks:
            yield chunk
        raise httpx.ReadError("connection reset mid-body")

    async def aclose(self) -> None:
        pass


async def test_stream_connection_drop_resumes_from_last_seen_seq():
    seen_headers: list[str | None] = []
    first = (
        json.dumps({"seq": 1, "type": "run.start", "run_id": "r", "goal": "g",
                    "depth": 0}) + "\n"
        + json.dumps({"seq": 2, "type": "think", "agent": "DRAFT", "text": "a"}) + "\n"
    ).encode()
    first_chunks = [first[i:i + 5] for i in range(0, len(first), 5)]
    second = (
        json.dumps({"seq": 3, "type": "run.done", "status": "ok", "steps": 2,
                    "duration_s": 0.2}) + '\n{"type":"stream.done"}\n'
    ).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(request.headers.get("last-event-id"))
        if len(seen_headers) == 1:
            return httpx.Response(200, stream=_FailingStream(first_chunks))
        return httpx.Response(200, stream=astream(second, chunk_size=3))

    client = _client(handler)
    events = [e async for e in
              client.stream(new_session_id(), last_event_id=None, max_hold_retries=2)]
    # the second request must resume at the last seq actually rendered
    assert seen_headers == [None, "2"]
    assert [e["seq"] for e in events] == [1, 2, 3]


async def test_stream_gives_up_after_repeated_drops():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = _client(handler)
    with pytest.raises(ArcenAPIError):
        async for _ in client.stream(new_session_id(), max_hold_retries=1):
            pass


async def test_rest_endpoints_pass_through():
    sid = new_session_id()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/run/r-9" and request.method == "DELETE":
            return httpx.Response(200, json={"ok": True, "interrupted": True})
        if path == "/api/sessions":
            return httpx.Response(200, json=[{"id": sid, "title": "t", "events": 3}])
        if path == f"/api/sessions/{sid}/events":
            return httpx.Response(200, json=[{"seq": 1, "type": "run.start"}])
        if path == "/api/config":
            return httpx.Response(200, json={"provider": {"name": "custom"}})
        if path == "/api/sandbox/status":
            return httpx.Response(200, json={"effective": "process", "degraded": True})
        raise AssertionError(f"unexpected {request.method} {path}")

    client = _client(handler)
    assert (await client.interrupt("r-9"))["interrupted"] is True
    sessions = await client.list_sessions()
    assert sessions[0]["id"] == sid
    assert (await client.session_events(sid))[0]["seq"] == 1
    assert (await client.get_config())["provider"]["name"] == "custom"
    assert (await client.sandbox_status())["degraded"] is True


async def test_error_endpoints_raise_with_detail():
    client = _client(lambda req: httpx.Response(500, json={"detail": "boom"}))
    with pytest.raises(ArcenAPIError) as exc:
        await client.list_sessions()
    assert exc.value.status == 500 and "boom" in str(exc.value)
