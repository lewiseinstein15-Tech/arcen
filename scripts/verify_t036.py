#!/usr/bin/env python3
"""ARCEN T-036 live verification — Settings view + config API + provider test.

Real chromium: open Settings from the sidebar, verify the four sections,
run Test Connection (green against the mock provider), Save (config.yaml
rewritten + toast), return to Chat and prove the next turn flows through
the saved provider.
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
    config_path = arcen_dir / "config.yaml"
    config_path.write_text(
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

            # open Settings from the sidebar
            page.click('[data-testid="nav-settings"]')
            page.wait_for_selector('[data-testid="settings-view"]', timeout=10000)
            check("settings view opens from the sidebar", True)
            for section in ("settings-provider", "settings-agents", "settings-sandbox", "settings-general"):
                check(f"section {section.split('-')[1]} renders", page.locator(f'[data-testid="{section}"]').count() == 1)

            provider_value = page.locator('[data-testid="provider-select"]').input_value()
            check("provider dropdown shows the current provider", provider_value == "custom", f"value={provider_value}")
            page.screenshot(path="/tmp/t036-settings.png")

            # Test Connection → green against the mock provider
            page.click('[data-testid="test-connection-btn"]')
            page.wait_for_selector('[data-testid="test-ok"]', timeout=20000)
            check("Test Connection shows green", page.locator('[data-testid="test-ok"]').count() == 1,
                  page.locator('[data-testid="test-ok"]').inner_text())

            # Save → config.yaml rewritten + toast
            mtime_before = config_path.stat().st_mtime_ns
            page.click('[data-testid="settings-save"]')
            page.wait_for_selector('[data-testid="toast"]', timeout=10000)
            check("Save shows the Saved toast", "Saved" in page.locator('[data-testid="toast"]').inner_text())
            deadline = time.time() + 5
            updated = False
            while time.time() < deadline:
                if config_path.stat().st_mtime_ns != mtime_before:
                    updated = True
                    break
                page.wait_for_timeout(100)
            check("config.yaml rewritten on Save", updated)
            body = config_path.read_text()
            check("persisted yaml holds the custom provider", "default: custom" in body and "base_urls" in body)
            check("persisted yaml is user-private (600)", (config_path.stat().st_mode & 0o777) == 0o600)
            page.screenshot(path="/tmp/t036-saved.png")

            # back to Chat — the turn flows through the saved provider
            page.click('[data-testid="nav-chat"]')
            page.wait_for_selector('[data-testid="composer"] textarea', timeout=10000)
            page.fill('[data-testid="composer"] textarea', "2+2")
            page.keyboard.press("Enter")
            page.wait_for_selector(".bot-message", timeout=30000)
            answer = page.locator(".bot-message .answer-prose").last.inner_text()
            check("'2+2' answers via the saved provider", "4" in answer, f"got: {answer[:60]!r}")

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
