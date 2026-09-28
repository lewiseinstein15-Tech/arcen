#!/usr/bin/env python3
"""ARCEN v0.1-final screenshot harness — all 10 approval shots, one live
session, real chromium, no page reloads except where noted.

Boots mock provider (:9377) + backend (:3002) + UI (:5173), then drives:
  01 sidebar with "+ New chat"          06 build-calculator plan + tools
  02 "hello" streaming live             07 scroll-up "↓ jump to latest" pill
  03 "2+2" answered directly            08 settings provider section
  04 "what is your name"                09 Test Connection green
  05 "explain closures" prose           10 three turns stacked chronologically
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "ui" / "screenshots" / "v0.1-final"
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
    SHOTS.mkdir(parents=True, exist_ok=True)

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

            # -- 01: sidebar with + New chat
            check("01 sidebar + new-chat button present", page.locator('[data-testid="new-chat-btn"]').count() == 1)
            page.screenshot(path=str(SHOTS / "01-sidebar-new-chat.png"))

            def send(goal: str) -> None:
                page.fill('[data-testid="composer"] textarea', goal)
                page.keyboard.press("Enter")

            def wait_new_answer(n_before: int, timeout: float = 40) -> None:
                deadline = time.time() + timeout
                while time.time() < deadline:
                    if page.locator(".bot-message").count() > n_before:
                        return
                    page.wait_for_timeout(120)

            # -- 02: "hello" streaming live (capture the generating state)
            n = page.locator(".bot-message").count()
            send("hello")
            captured = False
            deadline = time.time() + 5
            while time.time() < deadline:
                if page.locator('[data-testid="generating"]').count() > 0:
                    page.screenshot(path=str(SHOTS / "02-hello-live.png"))
                    captured = True
                    break
                page.wait_for_timeout(30)
            check("02 hello captured mid-stream (generating indicator)", captured)
            wait_new_answer(n)
            check("02 hello answered without refresh", page.locator(".bot-message .answer-prose").count() == 1)

            # -- 03: 2+2 direct
            n = page.locator(".bot-message").count()
            send("2+2")
            wait_new_answer(n)
            last = page.locator(".bot-message .answer-prose").last.inner_text()
            check("03 2+2 answered 4", "4" in last, f"got {last[:40]!r}")
            page.screenshot(path=str(SHOTS / "03-math-direct.png"))

            # -- 04: name
            n = page.locator(".bot-message").count()
            send("what is your name")
            wait_new_answer(n)
            last = page.locator(".bot-message .answer-prose").last.inner_text()
            check("04 name answered as ARCEN", "ARCEN" in last, f"got {last[:40]!r}")
            page.screenshot(path=str(SHOTS / "04-name-direct.png"))

            # -- 10: three turns stacked (hello / 2+2 / name all visible)
            page.evaluate("() => { const el = document.querySelector('[data-testid=\"stream\"]'); el.scrollTop = 0; }")
            page.wait_for_timeout(400)
            if page.locator('[data-testid="scroll-pill"]').count():
                page.evaluate("() => { const el = document.querySelector('[data-testid=\"stream\"]'); el.scrollTop = el.scrollHeight; el.scrollTop = el.scrollHeight; }")
                page.wait_for_timeout(300)
            page.screenshot(path=str(SHOTS / "10-turn-order.png"))
            pills = [p for p in page.locator(".user-pill .goal").all_inner_texts()
                     if p.strip() in ("hello", "2+2", "what is your name")]
            check("10 three user pills in chronological order", pills == ["hello", "2+2", "what is your name"], f"{pills}")

            # -- 05: closures prose
            n = page.locator(".bot-message").count()
            send("explain closures")
            wait_new_answer(n)
            last = page.locator(".bot-message .answer-prose").last.inner_text().lower()
            check("05 closures prose", "closure" in last, f"got {last[:40]!r}")
            page.screenshot(path=str(SHOTS / "05-closures-prose.png"))

            # -- 06: build calculator → plan + tools
            n = page.locator(".bot-message").count()
            send("build me a calculator")
            deadline = time.time() + 45
            while time.time() < deadline:
                if page.locator("article.plan").count() > 0 and page.locator("article.command").count() > 0:
                    break
                page.wait_for_timeout(200)
            has_plan = page.locator("article.plan").count() > 0
            has_cmd = page.locator("article.command").count() > 0
            check("06 calculator plan + tool blocks visible", has_plan and has_cmd,
                  f"plan={page.locator('article.plan').count()} cmd={page.locator('article.command').count()}")
            # keep the newest blocks in frame for the shot
            page.evaluate("() => { const el = document.querySelector('[data-testid=\"stream\"]'); el.scrollTop = el.scrollHeight; }")
            page.wait_for_timeout(300)
            page.screenshot(path=str(SHOTS / "06-build-calculator.png"))

            # -- 07: scroll-up pill
            page.evaluate("() => { const el = document.querySelector('[data-testid=\"stream\"]'); el.scrollTop = 0; }")
            page.wait_for_timeout(400)
            pill_ok = page.locator('[data-testid="scroll-pill"]').count() == 1
            check("07 pill visible when scrolled up", pill_ok)
            page.screenshot(path=str(SHOTS / "07-scroll-pill.png"))
            if pill_ok:
                page.click('[data-testid="scroll-pill"]')
                page.wait_for_timeout(500)

            # -- 08/09: settings
            page.click('[data-testid="nav-settings"]')
            page.wait_for_selector('[data-testid="settings-view"]', timeout=10000)
            page.screenshot(path=str(SHOTS / "08-settings-provider.png"))
            page.click('[data-testid="test-connection-btn"]')
            page.wait_for_selector('[data-testid="test-ok"]', timeout=20000)
            check("09 test connection green", page.locator('[data-testid="test-ok"]').count() == 1)
            page.screenshot(path=str(SHOTS / "09-settings-test.png"))

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
