"""Local mock server to verify composer→HTTP→NDJSON in a real terminal."""

from __future__ import annotations

import asyncio
import json

from aiohttp import web

turns: dict[str, dict] = {}
ready: dict[str, asyncio.Event] = {}


async def health(request):
    return web.json_response({"ok": True})


async def sandbox(request):
    return web.json_response({"effective": "docker", "degraded": False})


async def submit(request):
    data = await request.json()
    turns[data["session"]] = data
    ready.setdefault(data["session"], asyncio.Event()).set()
    return web.json_response({"run_id": "composer-demo", "session": data["session"]})


async def stream(request):
    session = request.query["session"]
    response = web.StreamResponse(headers={"Content-Type": "application/x-ndjson"})
    await response.prepare(request)
    await ready.setdefault(session, asyncio.Event()).wait()
    goal = turns[session]["goal"]
    events = [
        {"seq": 1, "type": "run.start", "run_id": "composer-demo", "goal": goal},
        {
            "seq": 2,
            "type": "think",
            "agent": "DRAFT",
            "text": "The server received the multiline goal. I will work through the request.",
        },
        {"seq": 3, "type": "answer", "text": "Goal received by the mock server."},
        {"seq": 4, "type": "run.done", "status": "ok"},
        {"type": "stream.done"},
    ]
    for event in events:
        await response.write((json.dumps(event) + "\n").encode())
        await asyncio.sleep(0.35)
    return response


app = web.Application()
app.router.add_get("/api/health", health)
app.router.add_get("/api/sandbox/status", sandbox)
app.router.add_get("/api/stream", stream)
app.router.add_post("/api/run", submit)
web.run_app(app, host="127.0.0.1", port=18713)
