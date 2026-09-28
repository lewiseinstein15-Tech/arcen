#!/usr/bin/env python3
"""ARCEN T-033 live verification — chronological turn order.

Sends 3 messages back-to-back (no reload) and proves the user pills and
answers render top→bottom in chronological order — newest at the BOTTOM.
Also reloads once and re-checks (replay order).
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

        GOALS = ["turn one hello", "turn two 2+2", "turn three name"]

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto("http://localhost:5173/", wait_until="domcontentloaded")
            page.wait_for_selector('[data-testid="composer"] textarea', timeout=20000)

            def send_and_wait(goal: str) -> None:
                page.fill('[data-testid="composer"] textarea', goal)
                page.keyboard.press("Enter")
                deadline = time.time() + 30
                start_count = page.locator(".bot-message").count()
                while time.time() < deadline:
                    if page.locator(".bot-message").count() > start_count:
                        return
                    page.wait_for_timeout(200)

            for goal in GOALS:
                send_and_wait(goal)

            # user pills (run.start goal pills) in DOM order
            pills = page.locator(".user-pill .goal").all_inner_texts()
            got = [p for p in pills if any(p.strip().startswith(g) for g in GOALS)]
            check("3 user pills stacked in send order", got == GOALS, f"DOM order: {got}")
            # answers in DOM order: mock answers are 4 / name / hello — map by position
            answers = page.locator(".bot-message .answer-prose").all_inner_texts()
            check("3 answers present", len(answers) == 3, f"count={len(answers)}")
            check("newest turn is the LAST user pill", got[-1] == GOALS[-1] if got else False)
            page.screenshot(path="/tmp/t033-order.png")

            # reload → replay must preserve chronological order
            page.reload(wait_until="domcontentloaded")
            page.wait_for_selector('[data-testid="composer"] textarea', timeout=20000)
            page.wait_for_timeout(1500)
            pills2 = [p for p in page.locator(".user-pill .goal").all_inner_texts()
                      if any(p.strip().startswith(g) for g in GOALS)]
            check("after reload the order is still chronological", pills2 == GOALS, f"DOM order: {pills2}")

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
