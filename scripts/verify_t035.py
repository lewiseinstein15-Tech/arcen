#!/usr/bin/env python3
"""ARCEN T-035 live verification — "+ New chat" button.

Real chromium: chat, then click the sidebar "+ New chat" → stream clears,
composer focused; the previous session remains in the sessions drawer;
the compact top-bar "+" does the same; an empty chat keeps its session.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKS: list[tuple[str, bool]] = []


def check(name, ok, detail=""):
    CHECKS.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def wait_http(url, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def main() -> int:
    arcen_dir = Path.home() / ".arcen"
    arcen_dir.mkdir(exist_ok=True)
    import shutil as _sh

    _sh.rmtree(arcen_dir / "sessions", ignore_errors=True)
    (arcen_dir / "config.yaml").write_text(
        "provider:\n"
        "  default: custom\n"
        "  models:\n"
        "    planner: mock-1\n"
        "    executor: mock-1\n"
        "    verifier: mock-1\n"
        "  api_keys:\n"
        "    custom: \"$ARCEN_MOCK_KEY\"\n"
        "  base_urls:\n"
        "    custom: http://127.0.0.1:9377/v1\n",
        encoding="utf-8",
    )
    os.environ["ARCEN_MOCK_KEY"] = "mock-secret-key"

    import shutil

    procs = []
    for pattern in ("uvicorn arcen.server.app", "mock_provider.py", "vite"):
        subprocess.run(["pkill", "-f", pattern], capture_output=True)
    time.sleep(1)
    try:
        procs.append(subprocess.Popen(
            [".venv/bin/python", "scripts/mock_provider.py", "9377"],
            cwd=ROOT, stdout=open("/tmp/mockp.log", "w"), stderr=subprocess.STDOUT, start_new_session=True))
        time.sleep(0.5)
        procs.append(subprocess.Popen(
            [".venv/bin/python", "-m", "uvicorn", "arcen.server.app:app", "--port", "3002"],
            cwd=ROOT, stdout=open("/tmp/arcen-backend.log", "w"), stderr=subprocess.STDOUT, start_new_session=True))
        if not wait_http("http://127.0.0.1:3002/api/health"):
            print("backend failed"); return 1
        procs.append(subprocess.Popen(
            [shutil.which("npm"), "run", "dev"],
            cwd=ROOT / "ui", stdout=open("/tmp/arcen-ui.log", "w"), stderr=subprocess.STDOUT, start_new_session=True))
        if not wait_http("http://localhost:5173/"):
            print("ui failed"); return 1

        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto("http://localhost:5173/", wait_until="domcontentloaded")
            page.wait_for_selector('[data-testid="composer"] textarea', timeout=20000)

            check("sidebar shows the + New chat button", page.locator('[data-testid="new-chat-btn"]').count() == 1)
            check("top bar shows the compact + button", page.locator('[data-testid="topbar-plus"]').count() == 1)

            # a chat turn first
            page.fill('[data-testid="composer"] textarea', "hello there")
            page.keyboard.press("Enter")
            page.wait_for_selector(".bot-message", timeout=30000)
            check("turn one answered", page.locator(".bot-message").count() == 1)

            # + New chat (sidebar)
            page.click('[data-testid="new-chat-btn"]')
            page.wait_for_timeout(600)
            check("stream cleared after new chat", page.locator(".bot-message").count() == 0)
            check("empty state visible", page.locator('[data-testid="stream-empty"]').count() == 1)
            focused = page.evaluate("() => document.activeElement && document.activeElement.dataset.testid === 'composer-input'")
            check("composer focused after new chat", focused)

            # empty chat: clicking again must not create a new session — still empty
            page.click('[data-testid="new-chat-btn"]')
            page.wait_for_timeout(300)

            # send in the fresh chat
            page.fill('[data-testid="composer"] textarea', "2+2")
            page.keyboard.press("Enter")
            page.wait_for_selector(".bot-message", timeout=30000)
            check("fresh chat accepts a new turn", page.locator(".bot-message").count() == 1)

            # the sessions drawer holds the previous chat
            page.click('[data-testid="session-chip"]')
            page.wait_for_timeout(800)
            rows = page.locator(".session-row").count()
            check("sessions drawer lists the previous chat", rows >= 2, f"rows={rows}")
            page.screenshot(path="/tmp/t035-drawer.png")
            page.click('[aria-label="close sessions"]')
            page.wait_for_timeout(300)

            # compact top-bar + also starts a new chat
            page.click('[data-testid="topbar-plus"]')
            page.wait_for_timeout(500)
            check("top-bar + clears the stream too", page.locator(".bot-message").count() == 0)

            browser.close()
    finally:
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass

    print(f"\n{sum(ok for _, ok in CHECKS)}/{len(CHECKS)} checks passed")
    return 0 if all(ok for _, ok in CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
