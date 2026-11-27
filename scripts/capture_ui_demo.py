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
OUT = Path("/workspace/project/arcen/docs/screenshots")

# Each scenario needs markers that only appear once the phase it proves is on
# screen; they come from the demo planner's titles and the real pytest output.
SCENARIOS = {
    "calc": {
        "goal": "build a calc module with tests and make them pass",
        "plan": "scaffold",
        "red": "test_add_positive",
        "fix": "file.edit",
        "prefix": "",
        "settings": True,
    },
    "geometry": {
        "goal": "create a geometry module with tests and make them pass",
        "plan": "create shapes.py",
        "red": "2 failed",
        "fix": "rewrite rectangle_area",
        "prefix": "07-geometry-",
        "settings": False,
    },
}
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
    name = sys.argv[1] if len(sys.argv) > 1 else "calc"
    scenario = SCENARIOS[name]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2)
        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_selector("textarea", timeout=60000)
        time.sleep(2)

        stop = threading.Event()
        watcher = threading.Thread(target=watch_containers, args=(stop,), daemon=True)
        watcher.start()

        page.fill("textarea", scenario["goal"])
        page.keyboard.press("Enter")

        page.wait_for_function(
            f"document.body.innerText.includes({scenario['plan']!r})", timeout=120000
        )
        page.evaluate("window.scrollTo(0, 0)")
        shot(page, scenario["prefix"] + "01-plan.png", full=False)

        page.wait_for_function(
            f"document.body.innerText.includes({scenario['red']!r})", timeout=120000
        )
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)
        shot(page, scenario["prefix"] + "02-red-tests.png")

        page.wait_for_function(
            f"document.body.innerText.includes({scenario['fix']!r})", timeout=120000
        )
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)
        shot(page, scenario["prefix"] + "03-replan-fix.png")

        page.wait_for_function(
            "document.body.innerText.includes('Verification passed')", timeout=180000
        )
        time.sleep(2)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)
        shot(page, scenario["prefix"] + "04-verified.png")
        print(page.inner_text("body")[-1200:], flush=True)

        stop.set()
        if not scenario["settings"]:
            browser.close()
            return 0
        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_selector("button:has-text('Settings')", timeout=60000)
        page.click("button:has-text('Settings')")
        time.sleep(3)
        shot(page, "05-sandbox-settings.png")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
