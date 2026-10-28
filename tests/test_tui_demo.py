"""TUI-03 — scripted demo app and headless test harness.

The demo must (1) play a full narrated turn with no server or TTY,
(2) exit 0 headlessly for CI, (3) be reachable through the ``arcen-tui
--demo`` entry point, and (4) expose the pilot/snapshot harness later card
tickets build on.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("textual")

import arcen.tui as tui_pkg
import arcen.tui.demo as demo_mod
from arcen.tui.demo import ANSWER, DemoApp

SNAPSHOT_ENABLED = bool(os.environ.get("ARCEN_SNAPSHOT"))


async def test_demo_plays_full_turn_headlessly():
    app = DemoApp(headless_mode=True)
    async with app.run_test(headless=True, size=(132, 44)):
        await app.wait_phase("finished", timeout=60)

    # the whole narration spine was populated
    assert len(app.narration.items) >= 10
    # rail reflects the completed run
    assert app.rail.steps_done == 4
    assert app.header.phase == "DONE"
    assert set(app.rail.tools) == {"bash", "file"}
    # answer card is the last card pushed
    from arcen.tui.demo import answer_card  # local import keeps test self-checking

    assert app.narration.items[-1] is not None
    assert "361 passed" in ANSWER
    # sanity: builder itself still renders
    assert answer_card() is not None


async def test_demo_traverses_every_phase_in_order():
    app = DemoApp(headless_mode=True)
    seen: list[str] = []
    async with app.run_test(headless=True, size=(132, 44)):
        for phase in ("draft", "forge", "forge_mid", "temper", "done", "finished"):
            await app.wait_phase(phase, timeout=60)
            seen.append(phase)
    assert seen == ["draft", "forge", "forge_mid", "temper", "done", "finished"]


def test_run_demo_headless_exits_zero():
    # no TTY path used in CI: app runs itself and calls exit() on completion
    assert demo_mod.run_demo(headless=True) == 0


def test_entry_point_routes_demo_flag(monkeypatch):
    called = {}

    def fake_run_demo(argv):
        called["argv"] = argv
        return 0

    monkeypatch.setattr(demo_mod, "run_demo", fake_run_demo)
    assert tui_pkg.main(["--demo"]) == 0
    assert called == {"argv": []}

    # extra flags are forwarded with --demo stripped
    called.clear()
    assert tui_pkg.main(["--demo", "--url", "http://x"]) == 0
    assert called["argv"] == ["--url", "http://x"]


def test_console_script_default_argv_routes_to_demo(monkeypatch):
    # Regression: the generated arcen-tui script calls main() with no
    # arguments, so the entry point must read sys.argv itself.
    monkeypatch.setattr("sys.argv", ["arcen-tui", "--demo"])
    called = {}

    def fake_run_demo(argv):
        called["argv"] = argv
        return 0

    monkeypatch.setattr(demo_mod, "run_demo", fake_run_demo)
    assert tui_pkg.main() == 0
    assert called == {"argv": []}


def test_demo_uses_only_frozen_theme_tokens():
    # every color alias in the module must resolve to a theme token value
    from arcen.tui.theme import TOKENS

    for alias in ("INK", "PANEL", "LINE", "MUTED", "BODY", "ACCENT", "CYAN",
                  "EMERALD", "ROSE", "AMBER", "THOUGHT", "MONO"):
        assert getattr(demo_mod, alias) in TOKENS.values()


@pytest.mark.skipif(not SNAPSHOT_ENABLED,
                    reason="set ARCEN_SNAPSHOT=1 to write SVG/PNG frames")
async def test_snapshot_helper_writes_frame(tmp_path):
    from _tui_snapshot import rasterize, save_svg

    app = DemoApp(headless_mode=True)
    async with app.run_test(headless=True, size=(132, 44)):
        await app.wait_phase("finished", timeout=60)
        svg = save_svg(app, tmp_path / "demo-finished.svg")

    assert svg.exists()
    png = rasterize(svg, tmp_path / "demo-finished.png")
    if png is not None:  # CairoSVG present
        assert png.exists() and png.stat().st_size > 1000
