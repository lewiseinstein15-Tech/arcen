"""Isolated mock configuration and sandbox endpoints for real-terminal capture."""

import asyncio

from aiohttp import web


async def health(request):
    return web.json_response({"ok": True})


async def sandbox(request):
    return web.json_response(
        {
            "backend": "auto",
            "effective": "process",
            "degraded": True,
            "docker_available": False,
            "image_present": False,
            "image": "arcen-sandbox:fixture",
            "reason": "docker daemon unavailable (fixture)",
        }
    )


async def config(request):
    return web.json_response(
        {
            "provider": {
                "name": "custom",
                "model": "example-model",
                "base_url": "https://example.invalid/v1",
                "api_key": "<redacted>",
            },
            "agents": {"draft": {"model": "inherit"}, "forge": {"model": "inherit"}},
            "sandbox": {"backend": "auto"},
            "mcps": [],
            "plugins": {"enabled": []},
        }
    )


async def stream(request):
    response = web.StreamResponse(headers={"Content-Type": "application/x-ndjson"})
    await response.prepare(request)
    while request.transport and not request.transport.is_closing():
        await asyncio.sleep(2)
        try:
            await response.write(b'{"type":"stream.ping"}\n')
        except ConnectionResetError:
            break
    return response


app = web.Application()
app.router.add_get("/api/health", health)
app.router.add_get("/api/sandbox/status", sandbox)
app.router.add_get("/api/config", config)
app.router.add_get("/api/stream", stream)
web.run_app(app, host="127.0.0.1", port=18715)
