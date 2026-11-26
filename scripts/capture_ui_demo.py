#!/usr/bin/env python3
"""Drive the ARCEN UI through a real turn and capture proof screenshots."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://work-1-skrtmjnssfqbhcsn.prod-runtime.all-hands.dev/"
GOAL = "build a calc module with tests and make them pass"
OUT = Path("/workspace/project/arcen/docs/screenshots")
VIEWPORT = {"width": 1440, "height": 1100}


def watch_containers(stop: threading.Event) -> None:
    """Record the first `docker ps` line that shows a live turn container."""
    seen = set()
    while not stop.is_set():
        out = subprocess.run(
            ["docker", "ps", "--format", "{{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Names}}"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        if "arcen-turn-" in out and out not in seen:
            seen.add(out)
            Path("/tmp/docker-ps.txt").write_text(out)
        time.sleep(0.3)


def shot(page, name: str, *, full: bool = True) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(OUT / name), full_page=full)
    print("captured", name, flush=True)


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2)
        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_selector("textarea", timeout=60000)
        time.sleep(2)

        stop = threading.Event()
        watcher = threading.Thread(target=watch_containers, args=(stop,), daemon=True)
        watcher.start()

        page.fill("textarea", GOAL)
        page.keyboard.press("Enter")

        page.wait_for_function("document.body.innerText.includes('scaffold')", timeout=120000)
        page.evaluate("window.scrollTo(0, 0)")
        shot(page, "01-plan.png", full=False)

        page.wait_for_function(
            "document.body.innerText.includes('test_add_positive')", timeout=120000
        )
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)
        shot(page, "02-red-tests.png")

        page.wait_for_function("document.body.innerText.includes('file.edit')", timeout=120000)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)
        shot(page, "03-replan-fix.png")

        page.wait_for_function(
            "document.body.innerText.includes('Verification passed')", timeout=180000
        )
        time.sleep(2)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)
        shot(page, "04-verified.png")
        print(page.inner_text("body")[-1200:], flush=True)

        stop.set()
        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_selector("button:has-text('Settings')", timeout=60000)
        page.click("button:has-text('Settings')")
        time.sleep(3)
        shot(page, "05-sandbox-settings.png")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
