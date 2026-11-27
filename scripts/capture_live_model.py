#!/usr/bin/env python3
"""Capture a turn planned by a real model through the UI.

Unlike capture_ui_demo.py this makes no assumption about step titles — the
model writes them. It waits on the lifecycle instead: DRAFT's plan lands,
execution runs, TEMPER signs off.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://work-1-skrtmjnssfqbhcsn.prod-runtime.all-hands.dev/"
GOAL = "create a module stats.py with mean, median and mode plus tests, run the tests and fix any failures"
OUT = Path("/workspace/project/arcen/docs/screenshots")
VIEWPORT = {"width": 1440, "height": 1100}


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

        page.fill("textarea", GOAL)
        page.keyboard.press("Enter")

        # the first tool row means the plan has landed and FORGE is running;
        # DRAFT's own line is replaced before a screenshot can catch it
        page.wait_for_function(
            "document.body.innerText.includes('file.write') || "
            "document.body.innerText.includes('bash')",
            timeout=300000,
        )
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(1)
        shot(page, "08-live-01-plan.png", full=False)

        time.sleep(10)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)
        shot(page, "08-live-02-executing.png")

        page.wait_for_function(
            "document.body.innerText.includes('Verification passed')", timeout=420000
        )
        time.sleep(2)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)
        shot(page, "08-live-03-verified.png")
        print(page.inner_text("body")[-1500:], flush=True)

        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_selector("button:has-text('Settings')", timeout=60000)
        page.click("button:has-text('Settings')")
        time.sleep(3)
        shot(page, "08-live-04-provider.png")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
