"""Async HTTP/NDJSON client for the ARCEN server API.

Mirrors the browser client (``ui/src/stream/reader.ts`` + the fetch calls
in ``ui/src/state``) against the documented routes in
``docs/BACKEND-SPEC.md``:

===========================  ==================================================
GET  /api/health             liveness probe
POST /api/run                start a turn → ``{run_id, session}``
DELETE /api/run/{run_id}     interrupt between steps
GET  /api/stream             held NDJSON stream (ping/done transport frames)
GET  /api/sessions           session meta, newest first
GET  /api/sessions/{id}/...  full event replay for a session
GET  /api/config             redacted config view
GET  /api/sandbox/status     docker/process backend decision
===========================  ==================================================

Only ``httpx`` is required here (a core ARCEN dependency) so the client is
unit-testable with ``httpx.MockTransport`` on a headless machine — no
Textual, no socket, no server.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Self

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:3002"
# Maximum UTF-8 bytes in one live NDJSON line, not including its newline.
MAX_LIVE_LINE_BYTES = 1024 * 1024
# Transport frames (BACKEND-SPEC Part 9): no ``seq`` — the app ignores them.
# stream.ping is an idle keepalive; stream.done is the clean close marker.
TRANSPORT_FRAMES = frozenset({"stream.ping", "stream.done"})
TERMINAL_EVENTS = frozenset({"run.done", "run.error"})


def is_app_event(value: object) -> bool:
    """Check the minimal live/replay envelope, not the event payload or origin."""
    return (
        type(value) is dict
        and type(value.get("type")) is str
        and bool(value["type"])
        and type(value.get("seq")) is int
        and value["seq"] > 0
    )


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


async def _bounded_live_lines(response: httpx.Response) -> AsyncIterator[bytes]:
    """Frame identity-encoded NDJSON without retaining an unbounded partial line.

    Reject an oversized frame rather than skipping it and silently advancing
    the resume cursor past an event the TUI did not see. This bounds only this
    parser's pending-line buffer, not HTTP transport allocation or replay.
    """
    pending = bytearray()
    async for chunk in response.aiter_bytes():
        start = 0
        while start < len(chunk):
            end = chunk.find(b"\n", start)
            if end < 0:
                end = len(chunk)
                complete = False
            else:
                complete = True
            if len(pending) + end - start > MAX_LIVE_LINE_BYTES:
                raise ArcenStreamProtocolError("live stream frame exceeds byte limit")
            pending.extend(memoryview(chunk)[start:end])
            if complete:
                yield bytes(pending)
                pending.clear()
            start = end + 1
    if pending:
        yield bytes(pending)


class ArcenAPIError(RuntimeError):
    """A non-2xx server reply, carrying the FastAPI ``detail`` when present."""

    def __init__(self, status: int, detail: str | None = None) -> None:
        self.status = status
        self.detail = detail
        super().__init__(detail or f"ARCEN server returned HTTP {status}")


class ArcenStreamProtocolError(ArcenAPIError):
    """A stream must be stopped until the peer's protocol issue is corrected."""

    def __init__(self, detail: str) -> None:
        super().__init__(0, detail)


def new_session_id() -> str:
    """A session id the server's UUID guard accepts (T-052).

    The web UI mints ``crypto.randomUUID()`` before its first run; the TUI
    does the same. The server's own ``s-<hex>`` fallback would fail the
    stream UUID check, so clients must send a real UUID.
    """
    return str(uuid.uuid4())


class ArcenClient:
    """Small async wrapper around the eleven ARCEN API routes."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = 30.0,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(
            base_url=self.base_url,
            # A held stream stays open for minutes; only bound connect/read
            # gaps, never the whole request (read=None disables the deadline).
            timeout=httpx.Timeout(timeout, connect=5.0, read=None, write=timeout, pool=timeout),
        )

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _detail(response: httpx.Response) -> str | None:
        """Extract FastAPI's ``{"detail": ...}`` without crashing on bodies."""
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError):
            return None
        if isinstance(body, dict) and isinstance(body.get("detail"), str):
            return body["detail"]
        return None

    async def _get_json(self, path: str) -> object:
        response = await self._http.get(path)
        if response.status_code >= 400:
            raise ArcenAPIError(response.status_code, self._detail(response))
        return response.json()

    # ------------------------------------------------------------------ routes

    async def health(self) -> bool:
        """True when the server answers /api/health. Never raises."""
        try:
            response = await self._http.get("/api/health")
        except httpx.HTTPError:
            return False
        if response.status_code != 200:
            return False
        try:
            return bool(response.json().get("ok"))
        except (json.JSONDecodeError, ValueError):
            return False

    async def submit_run(self, goal: str, session: str) -> dict:
        """POST /api/run — start a turn, returns ``{run_id, session}``.

        The server's error detail (e.g. the T-043 docker refusal) is
        surfaced verbatim via :class:`ArcenAPIError`.
        """
        response = await self._http.post("/api/run", json={"goal": goal, "session": session})
        if response.status_code >= 400:
            raise ArcenAPIError(response.status_code, self._detail(response))
        return response.json()

    async def interrupt(self, run_id: str) -> dict:
        """DELETE /api/run/{run_id} — request an between-steps interruption."""
        response = await self._http.delete(f"/api/run/{run_id}")
        if response.status_code >= 400:
            raise ArcenAPIError(response.status_code, self._detail(response))
        return response.json()

    async def list_sessions(self) -> list[dict]:
        data = await self._get_json("/api/sessions")
        return data if isinstance(data, list) else []

    async def session_events(self, session: str) -> list[dict]:
        """Full replay of one session (empty list for a fresh UUID — never 404)."""
        data = await self._get_json(f"/api/sessions/{session}/events")
        return data if isinstance(data, list) else []

    async def get_config(self) -> dict:
        data = await self._get_json("/api/config")
        return data if isinstance(data, dict) else {}

    async def put_config(self, config: dict) -> dict:
        """Update the server configuration; caller must preserve redacted secrets."""
        response = await self._http.put("/api/config", json=config)
        if response.status_code >= 400:
            raise ArcenAPIError(response.status_code, self._detail(response))
        data = response.json()
        return data if isinstance(data, dict) else {}

    async def sandbox_status(self) -> dict:
        data = await self._get_json("/api/sandbox/status")
        return data if isinstance(data, dict) else {}

    async def stream(
        self,
        session: str,
        last_event_id: int | None = None,
        *,
        max_hold_retries: int = 100,
    ) -> AsyncIterator[dict]:
        """Yield app events from held NDJSON; retry transport errors when allowed.

        Live-stream framing and reconnect behavior:

        - malformed UTF-8 or duplicate-key JSON lines are skipped;
        - oversized lines and non-identity content encodings fail the stream;
        - app events require a nonempty string type and positive integer seq;
        - seq-less transport frames (``stream.ping``) are invisible;
        - ``stream.done`` ends the iteration cleanly;
        - a 404 hold race is retried with backoff instead of surfacing;
        - HTTP 409 (Last-Event-ID compacted away) restarts once from zero;
        - ``run.done`` / ``run.error`` are yielded and then the stream is
          expected to close; an unexpected EOF just ends the iterator.
        """
        headers = {"Accept-Encoding": "identity"}
        if last_event_id is not None:
            headers["Last-Event-ID"] = str(last_event_id)
        url = f"/api/stream?session={session}"
        retries = 0
        seen_seq = last_event_id  # advances as events render → resume cursor

        while True:
            try:
                async with self._http.stream("GET", url, headers=headers) as response:
                    if response.status_code == 404:
                        # Held-stream race: the session exists nowhere yet.
                        # The modern server holds instead, but keep the
                        # browser's quiet-retry behavior for older builds.
                        retries += 1
                        if retries > max_hold_retries:
                            raise ArcenAPIError(404, "session never became streamable")
                        await response.aread()
                        continue
                    if response.status_code == 409:
                        # Compaction horizon: drop the resume hint, replay fresh.
                        headers.pop("Last-Event-ID", None)
                        await response.aread()
                        continue
                    if response.status_code >= 400:
                        await response.aread()
                        raise ArcenAPIError(
                            response.status_code,
                            self._detail(response) or "stream connection failed",
                        )

                    # Do not allow HTTP decompression to expand a small wire
                    # chunk before the parser can apply its line limit.
                    encoding = response.headers.get("content-encoding", "identity").strip().lower()
                    if encoding not in ("", "identity"):
                        raise ArcenStreamProtocolError("encoded live stream is not supported")
                    async for raw_line in _bounded_live_lines(response):
                        try:
                            line = raw_line.decode("utf-8", errors="strict")
                        except UnicodeDecodeError:
                            continue
                        event = self._parse_line(line)
                        if event is None:
                            continue
                        if event.get("type") == "stream.done":
                            return
                        if not is_app_event(event):
                            continue  # keepalives and malformed envelopes
                        seen_seq = event["seq"]
                        yield event
                    return
            except httpx.HTTPError as exc:
                # Connection dropped mid-turn: reconnect and resume from the
                # last seq actually rendered — the server replays the gap.
                retries += 1
                if retries > max_hold_retries:
                    raise ArcenAPIError(0, f"stream kept dropping: {exc}") from exc
                if seen_seq is not None:
                    headers["Last-Event-ID"] = str(seen_seq)
                continue

    @staticmethod
    def _parse_line(line: str) -> dict | None:
        """Parse one NDJSON line. Blank/malformed → None (stream never dies)."""
        line = line.strip()
        if not line:
            return None
        try:
            data = json.loads(line, object_pairs_hook=_unique_pairs)
        except (ValueError, RecursionError):
            return None
        return data if isinstance(data, dict) else None
