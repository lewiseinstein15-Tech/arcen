"""Read-only configuration and sandbox modals; no secret disclosure."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from rich.console import Console

pytest.importorskip("textual")
from arcen.tui.client import ArcenClient
from arcen.tui.live import LiveApp
from arcen.tui.modals import InfoScreen, config_view, sandbox_view


def test_views_redact_secret_and_url_credentials():
    console = Console(record=True, width=100, color_system=None)
    console.print(
        config_view(
            {
                "provider": {
                    "name": "custom",
                    "model": "demo",
                    "base_url": "https://user:pass@example.com/api?token=secret#x",
                    "api_key": "literal-secret",
                },
                "agents": {},
                "sandbox": {"backend": "auto"},
            }
        )
    )
    console.print(sandbox_view({"effective": "process", "degraded": True, "reason": "no docker"}))
    text = console.export_text()
    assert "<redacted>" in text and "https://example.com/api" in text
    assert "literal-secret" not in text and "pass" not in text and "token=secret" not in text
    assert "DEGRADED" in text and "process" in text


async def test_config_and_sandbox_open_close_and_partial_failure():
    calls = []

    async def handler(req):
        calls.append(req.url.path)
        if req.url.path == "/api/health":
            return httpx.Response(200, json={"ok": True})
        if req.url.path == "/api/config":
            return httpx.Response(200, json={"provider": {"name": "mock", "api_key": "sensitive"}})
        if req.url.path == "/api/sandbox/status":
            return httpx.Response(
                200, json={"effective": "process", "degraded": True, "reason": "no daemon"}
            )
        if req.url.path == "/api/stream":

            class Hold(httpx.AsyncByteStream):
                async def __aiter__(self):
                    await asyncio.Event().wait()
                    yield b""

            return httpx.Response(200, stream=Hold())
        return httpx.Response(404)

    http = httpx.AsyncClient(base_url="http://mock", transport=httpx.MockTransport(handler))
    app = LiveApp(client=ArcenClient("http://mock", http=http), retry_seconds=0.01)
    try:
        async with app.run_test(size=(132, 44)) as pilot:
            await pilot.press("ctrl+o")
            await pilot.pause()
            assert isinstance(app.screen, InfoScreen)
            assert "/api/config" in calls and "/api/sandbox/status" in calls
            body = app.screen.query_one("#info-body")
            console = Console(record=True, width=100, color_system=None)
            console.print(body.content)
            shown = console.export_text()
            assert "CONFIGURATION" in shown and "SANDBOX" in shown
            assert "sensitive" not in shown and "<redacted>" in shown and "DEGRADED" in shown
            await pilot.press("enter")
            assert not isinstance(app.screen, InfoScreen)
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert isinstance(app.screen, InfoScreen) and app.screen.sandbox_only
            await pilot.press("escape")
            assert not isinstance(app.screen, InfoScreen)
    finally:
        await http.aclose()


async def test_modal_reports_api_errors_without_crashing():
    async def handler(req):
        return httpx.Response(503, json={"detail": "temporarily unavailable"})

    http = httpx.AsyncClient(base_url="http://mock", transport=httpx.MockTransport(handler))
    app = LiveApp(client=ArcenClient("http://mock", http=http), retry_seconds=60)
    try:
        async with app.run_test() as pilot:
            await pilot.press("ctrl+o")
            await pilot.pause()
            console = Console(record=True, width=100, color_system=None)
            console.print(app.screen.query_one("#info-body").content)
            text = console.export_text()
            assert "Configuration unavailable" in text and "Sandbox unavailable" in text
            await pilot.press("escape")
    finally:
        await http.aclose()
