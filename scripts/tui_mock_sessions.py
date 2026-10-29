"""Local server exposing one isolated recorded session for TUI-14 captures."""

import asyncio
import json
from pathlib import Path

from aiohttp import web

SID = "11111111-1111-4111-8111-111111111111"
EVENTS = [
    json.loads(line)
    for line in (Path(__file__).resolve().parents[1] / "tests/fixtures/tui/server-replan.jsonl")
    .read_text()
    .splitlines()
]


async def health(request):
    return web.json_response({"ok": True})


async def sandbox(request):
    return web.json_response({"effective": "docker", "degraded": False})


async def sessions(request):
    return web.json_response(
        [{"id": SID, "title": "Replan and verify (fixture)", "events": len(EVENTS)}]
    )


async def history(request):
    return web.json_response(EVENTS if request.match_info["id"] == SID else [])


async def stream(request):
    response = web.StreamResponse(headers={"Content-Type": "application/x-ndjson"})
    await response.prepare(request)
    while not request.transport.is_closing():
        await asyncio.sleep(2)
        try:
            await response.write(b'{"type":"stream.ping"}\n')
        except ConnectionResetError:
            break
    return response


app = web.Application()
app.router.add_get("/api/health", health)
app.router.add_get("/api/sandbox/status", sandbox)
app.router.add_get("/api/sessions", sessions)
app.router.add_get("/api/sessions/{id}/events", history)
app.router.add_get("/api/stream", stream)
web.run_app(app, host="127.0.0.1", port=18714)
