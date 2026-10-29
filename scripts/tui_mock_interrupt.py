"""Local, deterministic mock for TUI-12 terminal verification; no model access."""

import asyncio
import json

from aiohttp import web

stopped = asyncio.Event()


async def health(request):
    return web.json_response({"ok": True})


async def sandbox(request):
    return web.json_response({"effective": "docker", "degraded": False})


async def interrupt(request):
    stopped.set()
    return web.json_response({"ok": True, "interrupted": True})


async def stream(request):
    response = web.StreamResponse(headers={"Content-Type": "application/x-ndjson"})
    await response.prepare(request)

    async def send(event):
        await response.write((json.dumps(event) + "\n").encode())

    await send(
        {
            "seq": 1,
            "type": "run.start",
            "run_id": "verify-interrupt",
            "goal": "Safely interrupt a running turn",
        }
    )
    await send(
        {
            "seq": 2,
            "type": "think",
            "agent": "DRAFT",
            "text": "Working through the current step. The server waits for a confirmed interrupt.",
        }
    )
    await stopped.wait()
    await send({"seq": 3, "type": "run.done", "status": "interrupted"})
    await send({"type": "stream.done"})
    return response


app = web.Application()
app.router.add_get("/api/health", health)
app.router.add_get("/api/sandbox/status", sandbox)
app.router.add_get("/api/stream", stream)
app.router.add_delete("/api/run/{run_id}", interrupt)
web.run_app(app, host="127.0.0.1", port=18712)
