"""Headless screenshot capture for the ARCEN TUI prototype.

Runs the demo app without a terminal, waits at scripted checkpoints, and
writes self-contained SVG frames into prototype/shots/.
"""
from __future__ import annotations

import asyncio
import pathlib

from arcen_tui_demo import DemoApp

SHOTS = pathlib.Path(__file__).parent / "shots"
SIZE = (132, 44)

FRAMES = [
    ("forge",     "frame-1-draft-planning.svg"),
    ("forge_mid", "frame-2-forge-executing.svg"),
    ("finished",  "frame-3-complete-run.svg"),
]


async def main() -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    app = DemoApp()
    async with app.run_test(headless=True, size=SIZE):
        for phase, filename in FRAMES:
            await app.wait_phase(phase, timeout=90)
            await asyncio.sleep(0.35)  # let the final paint settle
            target = SHOTS / filename
            app.save_screenshot(filename=filename, path=str(SHOTS))
            print(f"saved {target}")
    print("done")


if __name__ == "__main__":
    asyncio.run(main())
