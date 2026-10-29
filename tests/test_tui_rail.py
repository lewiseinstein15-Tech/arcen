"""TUI-05 — run-state rail: state-dict → rendered panel assertions.

The rail is a pure function of ``RailState``: most tests build state dicts
and assert on the Rich renderables without an app; one headless pilot test
covers mounting, live re-render and the narrow-terminal collapse.
"""

from __future__ import annotations

import pytest

pytest.importorskip("textual")

from rich.console import Console

from arcen.tui.app import RAIL_COLLAPSE_WIDTH
from arcen.tui.theme import TOKENS
from arcen.tui.views.rail import (
    BAR_WIDTH,
    DEFAULT_TOKEN_LIMIT,
    PHASES,
    RailState,
    RunStateRail,
)


def _plain(widget) -> str:
    console = Console(record=True, width=60)
    console.print(widget.render())
    return console.export_text()


def _style_hexes(text) -> set[str]:
    found: set[str] = set()
    for _s, _e, style in text.spans:
        color = getattr(style, "color", None)
        if color is not None and color.triplet is not None:
            r, g, b = color.triplet
            found.add(f"#{r:02x}{g:02x}{b:02x}")
    return found


# ── structure ───────────────────────────────────────────────────────────────
def test_default_rail_renders_every_block():
    text = _plain(RunStateRail())
    for heading in ("RUN PROGRESS", "PHASES", "CONTEXT WINDOW", "SPEND",
                    "TOOLS", "ENVIRONMENT", "HARNESS"):
        assert heading in text
    # idle rail: no run yet, so step 0/0 and an em-dash where data is absent
    assert "step 0/0" in text
    assert "—" in text


def test_rail_state_is_plain_dataclass_with_document_defaults():
    state = RailState()
    assert state.steps_done == 0
    assert state.token_limit == DEFAULT_TOKEN_LIMIT == 128_000
    assert state.tools == [] and state.harness is None


# ── progress + meters ───────────────────────────────────────────────────────
def test_state_dict_drives_step_counter_and_progress_bar():
    rail = RunStateRail(steps_total=4)
    rail.apply_state({"steps_done": 2})
    assert rail.steps_done == 2
    assert "step 2/4" in _plain(rail)

    bar = rail._meter(2 / 4, TOKENS["accent"])
    assert bar.plain.count("█") == BAR_WIDTH // 2
    assert bar.plain.count("░") == BAR_WIDTH // 2


def test_meter_clamps_out_of_range_fractions():
    rail = RunStateRail()
    assert rail._meter(5, TOKENS["cyan"]).plain.count("█") == BAR_WIDTH
    assert rail._meter(-1, TOKENS["cyan"]).plain.count("█") == 0


def test_context_meter_label_uses_thousands_separators():
    rail = RunStateRail(steps_total=4)
    rail.apply_state({"tokens": 6_400})
    text = _plain(rail)
    assert "6,400 / 128,000 tok" in text
    meter = rail._meter(6_400 / DEFAULT_TOKEN_LIMIT, TOKENS["cyan"])
    assert meter.plain.count("█") == round(6_400 / DEFAULT_TOKEN_LIMIT * BAR_WIDTH)


def test_spend_is_four_decimal_usd():
    rail = RunStateRail(steps_total=4)
    rail.apply_state({"cost_usd": 0.0412})
    assert "$0.0412" in _plain(rail)


# ── phase tracker ───────────────────────────────────────────────────────────
def test_phase_name_and_index_both_drive_the_tracker():
    rail = RunStateRail(steps_total=4)
    rail.apply_state({"phase": "FORGE"})  # name → index
    assert rail.phase_idx == PHASES.index("FORGE") == 1

    timeline = rail._phase_timeline().plain
    assert "● DRAFT" in timeline      # finished phase
    assert "◐ FORGE" in timeline      # active phase
    assert "○ TEMPER" in timeline     # pending phase
    assert "○ DONE" in timeline

    rail.apply_state({"phase_idx": 3})  # raw index overrides
    assert rail.phase_idx == 3


def test_unknown_phase_name_is_ignored_not_raised():
    rail = RunStateRail(steps_total=4)
    rail.apply_state({"phase": "FORGE"})
    rail.apply_state({"phase": "NOPE"})
    assert rail.phase_idx == 1  # unchanged


def test_idle_rail_shows_all_phases_pending():
    timeline = RunStateRail()._phase_timeline()
    assert "◐" not in timeline.plain
    assert timeline.plain.count("○") == len(PHASES)


# ── tools / environment / harness ───────────────────────────────────────────
def test_tool_chips_dedupe_and_sort():
    rail = RunStateRail(steps_total=4)
    rail.apply_state({"tools": ["file", "bash", "bash", "file"]})
    chips = rail._tool_chips().plain
    # sorted unique chips, bash before file
    assert chips.index("bash") < chips.index("file")
    assert chips.count("bash") == 1 and chips.count("file") == 1
    assert "—" in _plain(RunStateRail())  # no tools yet


def test_environment_nested_dict_and_harness():
    rail = RunStateRail()
    rail.apply_state({
        "environment": {
            "sandbox": "docker",
            "network": "on",
            "workdir": "/work",
        },
        "harness": "adopted@abc123",
    })
    text = _plain(rail)
    assert "docker" in text and "/work" in text and "adopted@abc123" in text
    # network on is deliberately not the healthy-green "off" style
    assert rail.state.network == "on"
    assert rail.state.harness == "adopted@abc123"


def test_network_placeholder_is_neutral_not_warning():
    rail = RunStateRail()
    assert rail._network_style("—") == TOKENS["muted"]
    assert rail._network_style("off") == TOKENS["emerald"]
    assert rail._network_style("on") == TOKENS["amber"]
    assert rail.state.network == "—"


def test_unknown_state_keys_are_ignored():
    # forward-compatibility: additive ARCEN² fields must not crash the rail
    rail = RunStateRail(steps_total=4)
    rail.apply_state({"steps_done": 1, "harness.propose": [], "canary": {"x": 1}})
    assert rail.steps_done == 1
    assert "step 1/4" in _plain(rail)


# ── theme discipline ────────────────────────────────────────────────────────
def test_rail_colors_resolve_to_frozen_tokens():
    rail = RunStateRail(steps_total=4)
    rail.apply_state({"phase": "TEMPER", "tools": ["bash"], "tokens": 1000,
                      "harness": "adopted@a1f3c9"})
    allowed = {v.lower() for v in TOKENS.values()}
    for component in (rail._phase_timeline(),
                      rail._meter(0.5, TOKENS["accent"]),
                      rail._tool_chips()):
        assert _style_hexes(component) <= allowed


# ── demo-facing attribute compatibility ─────────────────────────────────────
def test_demo_style_attribute_mutation_works():
    rail = RunStateRail(steps_total=4)
    rail.steps_done = 3
    rail.tokens = 99
    rail.cost = 0.01
    rail.tools.append("bash")
    assert rail.state.steps_done == 3
    text = _plain(rail)
    assert "step 3/4" in text
    assert "99 / 128,000 tok" in text
    assert "$0.0100" in text
    assert "bash" in text


# ── headless pilot: mount, live update, collapse ────────────────────────────
async def test_rail_mounts_updates_and_collapses_in_shell():
    from arcen.tui.app import ArcenApp

    app = ArcenApp()
    async with app.run_test(headless=True, size=(132, 44)) as pilot:
        await pilot.pause()
        rail = app.query_one("#rail", RunStateRail)
        assert not app.rail_collapsed

        rail.apply_state({
            "steps_done": 1, "steps_total": 4, "phase": "FORGE",
            "tokens": 1820, "cost_usd": 0.0041, "tools": ["bash"],
        })
        await pilot.pause()
        assert rail.steps_done == 1 and rail.phase_idx == 1
        assert "step 1/4" in _plain(rail)

        await pilot.resize_terminal(RAIL_COLLAPSE_WIDTH - 1, 24)
        await pilot.pause()
        assert app.rail_collapsed
        assert rail.display is False
