"""Capture the live UI proving the reasoning layer, into docs/screenshots.

Run against a booted server (arcen serve, which also serves ui/dist):

    python scripts/capture_reasoning_shots.py --base http://127.0.0.1:12000

Every image is a real browser render of a real turn against the real
backend and the configured provider — nothing is drawn by hand.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:12000")
    parser.add_argument("--goal", default="create fizzbuzz.py with fizzbuzz(n) and test_fizzbuzz.py, then run pytest")
    parser.add_argument("--timeout", type=float, default=240.0)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 960})
        # networkidle never settles: the UI holds the event stream open
        page.goto(args.base, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        page.screenshot(path=str(OUT / "11-reasoning-01-idle.png"))

        box = page.locator("textarea").first
        box.fill(args.goal)
        box.press("Enter")

        deadline = args.timeout
        marker = ("verified", "verification", "passed", "run complete")
        waited = 0.0
        while waited < deadline:
            page.wait_for_timeout(2000)
            waited += 2
            text = page.inner_text("body").lower()
            if any(word in text for word in marker) and "running" not in text:
                break
        page.wait_for_timeout(2500)
        page.screenshot(path=str(OUT / "11-reasoning-02-turn.png"))

        # the turn scrolls; capture the plan and the verification too
        page.mouse.move(700, 400)
        for _ in range(8):
            page.mouse.wheel(0, -600)
            page.wait_for_timeout(150)
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT / "11-reasoning-03-plan.png"))

        body = page.inner_text("body")
        browser.close()

    checks = {
        "complexity note": "Complexity" in body,
        "verification": "verif" in body.lower(),
    }
    for name, ok in checks.items():
        print(f"{'ok ' if ok else 'MISSING'} {name}")
    if not all(checks.values()):
        return 1
    print(f"wrote screenshots to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
