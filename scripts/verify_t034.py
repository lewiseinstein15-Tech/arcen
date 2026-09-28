#!/usr/bin/env python3
"""ARCEN T-034 live verification — auto-scroll + jump-to-latest pill.

Real chromium, no reloads:
  1. While pinned, the stream follows growth: distance-from-bottom stays
     within the 100px threshold while turns stream in.
  2. Scrolling up mid-session → "↓ jump to latest" pill appears.
  3. Clicking the pill → snaps back to the bottom, pill disappears.
  4. Scrolling back to the bottom manually → pinning resumes (next turn
     follows without the pill reappearing).
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


DIST = "() => { const el = document.querySelector('[data-testid=\"stream\"]'); return el.scrollHeight - el.scrollTop - el.clientHeight; }"


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
            page = browser.new_page(viewport={"width": 1440, "height": 700})
            page.goto("http://localhost:5173/", wait_until="domcontentloaded")
            page.wait_for_selector('[data-testid="composer"] textarea', timeout=20000)

            def send(goal: str) -> None:
                page.fill('[data-testid="composer"] textarea', goal)
                page.keyboard.press("Enter")

            def wait_new_answer(n_before: int, timeout: float = 30) -> None:
                deadline = time.time() + timeout
                while time.time() < deadline:
                    if page.locator(".bot-message").count() > n_before:
                        return
                    page.wait_for_timeout(150)

            # -- grow content with several turns; sample distance while pinned
            max_dist = 0.0
            for i in range(4):
                before = page.locator(".bot-message").count()
                send("explain closures" if i % 2 == 0 else "hello")
                page.wait_for_timeout(120)
                deadline = time.time() + 6
                while time.time() < deadline:
                    d = page.evaluate(DIST)
                    max_dist = max(max_dist, d)
                    if page.locator(".bot-message").count() > before and page.locator('[data-testid="generating"]').count() == 0:
                        break
                    page.wait_for_timeout(100)
            tall = page.evaluate("() => { const el = document.querySelector('[data-testid=\"stream\"]'); return el.scrollHeight; }")
            check("content taller than the viewport", tall > 700, f"scrollHeight={tall:.0f}")
            check("pinned follow keeps distance <= 100px while streaming", max_dist <= 100, f"max distance {max_dist:.0f}px")

            # -- scroll up mid-session → pill
            page.evaluate("() => { const el = document.querySelector('[data-testid=\"stream\"]'); el.scrollTop = 0; }")
            page.wait_for_timeout(400)
            pill = page.locator('[data-testid="scroll-pill"]')
            check("'jump to latest' pill appears when scrolled up", pill.count() > 0 and "jump to latest" in pill.inner_text())
            page.screenshot(path="/tmp/t034-pill.png")

            # -- click pill → back to bottom, pill gone
            pill.click()
            page.wait_for_timeout(700)
            d = page.evaluate(DIST)
            check("pill click snaps to bottom (distance <= 100)", d <= 100, f"distance {d:.0f}px")
            check("pill disappears after the jump", page.locator('[data-testid="scroll-pill"]').count() == 0)

            # -- scroll up again, then manually back to bottom → pinning resumes
            page.evaluate("() => { const el = document.querySelector('[data-testid=\"stream\"]'); el.scrollTop = 100; }")
            page.wait_for_timeout(300)
            check("pill reappears after scrolling up again", page.locator('[data-testid="scroll-pill"]').count() > 0)
            page.evaluate("() => { const el = document.querySelector('[data-testid=\"stream\"]'); el.scrollTop = el.scrollHeight; }")
            page.wait_for_timeout(300)
            check("manual return to bottom dismisses the pill", page.locator('[data-testid="scroll-pill"]').count() == 0)

            # -- pinned again: the next turn must follow
            before = page.locator(".bot-message").count()
            send("hello")
            max_follow = 0.0
            deadline = time.time() + 10
            while time.time() < deadline:
                max_follow = max(max_follow, page.evaluate(DIST))
                if page.locator(".bot-message").count() > before and page.locator('[data-testid="generating"]').count() == 0:
                    break
                page.wait_for_timeout(100)
            check("pinning resumes: next turn follows without the pill", max_follow <= 100 and page.locator('[data-testid="scroll-pill"]').count() == 0, f"max distance {max_follow:.0f}px")

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
