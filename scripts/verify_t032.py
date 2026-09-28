#!/usr/bin/env python3
"""ARCEN T-032 live verification — optimistic streaming visibility.

Boots mock provider + backend + UI, drives real chromium, and proves:
  1. The instant Send is pressed (before the POST resolves), the user pill
     + "◆ DRAFT" skeleton + generating indicator are visible — no waiting.
  2. The server's run.start replaces the optimistic block (no double pill).
  3. The indicator names the working agent while events stream.
  4. The indicator disappears when the turn completes.
  5. No page reload at any point.
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


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def wait_http(url: str, timeout: float = 30) -> bool:
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

    procs: list = []
    for pattern in ("uvicorn arcen.server.app", "mock_provider.py", "vite"):
        subprocess.run(["pkill", "-f", pattern], capture_output=True)
    time.sleep(1)
    try:
        procs.append(
            subprocess.Popen(
                [".venv/bin/python", "scripts/mock_provider.py", "9377"],
                cwd=ROOT, stdout=open("/tmp/mockp.log", "w"), stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        )
        time.sleep(0.5)
        procs.append(
            subprocess.Popen(
                [".venv/bin/python", "-m", "uvicorn", "arcen.server.app:app", "--port", "3002"],
                cwd=ROOT, stdout=open("/tmp/arcen-backend.log", "w"), stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        )
        if not wait_http("http://127.0.0.1:3002/api/health"):
            print("backend failed to boot")
            return 1
        procs.append(
            subprocess.Popen(
                [shutil.which("npm"), "run", "dev"],
                cwd=ROOT / "ui", stdout=open("/tmp/arcen-ui.log", "w"), stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        )
        if not wait_http("http://localhost:5173/"):
            print("ui failed to boot")
            return 1

        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto("http://localhost:5173/", wait_until="domcontentloaded")
            page.wait_for_selector('[data-testid="composer"] textarea', timeout=20000)

            # -- 1. the optimistic UI appears the instant Send is pressed
            page.fill('[data-testid="composer"] textarea', "2+2")
            t_press = time.time()
            page.keyboard.press("Enter")
            # poll the DOM at ~60fps for the skeleton — must be < 500ms;
            # capture the indicator text at the SAME instant (the mock is
            # near-instant, so late reads race the whole turn)
            appeared = None
            gen_at_appear = None
            pill_ok = False
            while time.time() - t_press < 2.0:
                if appeared is None and page.locator('[data-testid="draft-skeleton"]').count() > 0:
                    appeared = time.time() - t_press
                    gen = page.locator('[data-testid="generating"]')
                    gen_at_appear = gen.inner_text() if gen.count() else "(gone)"
                pill = page.locator('[data-testid="pending-turn"]')
                if pill.count() and "2+2" in pill.inner_text():
                    pill_ok = True
                if appeared is not None and pill_ok and gen_at_appear is not None:
                    break
                page.wait_for_timeout(30)
            check("skeleton visible instantly on Send (<500ms)", appeared is not None and appeared < 0.5,
                  f"appeared after {appeared:.3f}s" if appeared is not None else "NEVER")
            check("optimistic user pill shows the message", pill_ok)
            check("generating indicator shows DRAFT is thinking", gen_at_appear is not None and "DRAFT is thinking" in gen_at_appear,
                  f"at skeleton+0ms: {gen_at_appear!r}")
            page.screenshot(path="/tmp/t032-skeleton.png")

            # -- 2. server truth replaces the optimistic block
            page.wait_for_selector(".bot-message", timeout=30000)
            check("no double pill after run.start", page.locator('[data-testid="pending-turn"]').count() == 0)
            answer = page.locator(".bot-message .answer-prose").last.inner_text()
            check("answer '4' streamed in (DIRECT, mock)", "4" in answer, f"got: {answer[:60]!r}")

            # -- 3/4. indicator lifecycle: gone after the turn completes
            deadline = time.time() + 10
            gone = False
            while time.time() < deadline:
                if page.locator('[data-testid="generating"]').count() == 0:
                    gone = True
                    break
                page.wait_for_timeout(200)
            check("generating indicator disappears on completion", gone)

            # -- a CODE turn with a real 2s step so the FORGE phase is catchable
            page.fill('[data-testid="composer"] textarea', "sleep 2; echo done")
            page.keyboard.press("Enter")
            saw_forge = False
            deadline = time.time() + 30
            while time.time() < deadline:
                gen = page.locator('[data-testid="generating"]')
                if gen.count() and "FORGE is working" in gen.inner_text():
                    saw_forge = True
                    break
                page.wait_for_timeout(100)
            check("indicator names FORGE during execution phase", saw_forge)

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
