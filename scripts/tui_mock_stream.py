"""Isolated local HTTP stream fixture used for TUI-11 real-terminal captures.

Usage: python scripts/tui_mock_stream.py. The first response closes early;
the next resumes from Last-Event-ID and terminates normally. This is a mock
server replaying the isolated recorded fixture, not a model or live backend.
"""

import asyncio
import json
from pathlib import Path

from aiohttp import web

DATA = [
    json.loads(line)
    for line in (Path(__file__).resolve().parents[1] / "tests/fixtures/tui/server-replan.jsonl")
    .read_text()
    .splitlines()
]


async def health(r):
    return web.json_response({"ok": True})


async def sandbox(r):
    return web.json_response(
        {"effective": "process", "degraded": True, "reason": "docker unavailable (mock server)"}
    )


async def history(r):
    return web.json_response([])


async def stream(r):
    last = int(r.headers.get("Last-Event-ID", "0"))
    resp = web.StreamResponse(headers={"Content-Type": "application/x-ndjson"})
    await resp.prepare(r)
    items = [e for e in DATA if e["seq"] > last]
    limit = 5 if last == 0 else len(items)
    for event in items[:limit]:
        await asyncio.sleep(0.5)
        await resp.write((json.dumps(event) + "\n").encode())
    if last:
        await resp.write(b'{"type":"stream.done"}\n')
    await resp.write_eof()
    return resp


app = web.Application()
app.router.add_get("/api/health", health)
app.router.add_get("/api/sandbox/status", sandbox)
app.router.add_get("/api/sessions/{id}/events", history)
app.router.add_get("/api/stream", stream)
web.run_app(app, host="127.0.0.1", port=18711)
