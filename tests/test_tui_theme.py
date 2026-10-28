"""TUI-02 — design tokens and xterm-256 fallbacks.

The theme module must not require Textual; these tests run on Rich alone and
pin both the truecolor tokens and the deterministic 256-color table.
"""

from __future__ import annotations

import re

import pytest

pytest.importorskip("rich")

from arcen.tui import theme
from arcen.tui.theme import (
    ANSI256_FALLBACKS,
    CARD_ACCENTS,
    FONT_STACK,
    PHASE_COLORS,
    STATUS_COLORS,
    TOKENS,
    nearest_ansi256,
    resolve,
)

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def test_every_token_is_valid_hex():
    assert TOKENS  # non-empty
    for name, value in TOKENS.items():
        assert HEX.match(value), f"{name} has invalid hex {value!r}"


def test_every_token_has_a_256_fallback_in_cube_or_gray_range():
    assert set(ANSI256_FALLBACKS) == set(TOKENS)
    for name, code in ANSI256_FALLBACKS.items():
        assert 16 <= code <= 255, f"{name} fallback {code} outside 16..255"


@pytest.mark.parametrize(
    "hex_color,expected",
    [
        ("#000000", 16),    # cube black
        ("#FFFFFF", 231),   # cube white (5,5,5)
        ("#0000FF", 21),    # cube blue axis
        ("#FF0000", 196),   # cube red axis (5,0,0)
        ("#808080", 244),   # grayscale ramp, value 128
    ],
)
def test_nearest_ansi256_known_anchors(hex_color, expected):
    assert nearest_ansi256(hex_color) == expected


def test_fallback_computation_is_stable():
    # repeated calls and the frozen table must agree exactly
    for name, hex_color in TOKENS.items():
        assert nearest_ansi256(hex_color) == ANSI256_FALLBACKS[name]


def test_semantic_tables_reference_real_tokens():
    for table in (PHASE_COLORS, STATUS_COLORS, CARD_ACCENTS):
        for alias, token in table.items():
            assert token in TOKENS, f"alias {alias!r} points at unknown token"


def test_phase_table_covers_all_agent_phases():
    assert set(PHASE_COLORS) == {"DRAFT", "FORGE", "TEMPER", "DONE", "IDLE", "ERROR"}


def test_resolve_truecolor_and_256():
    tc = resolve("accent")
    assert tc.color_system == "truecolor"
    assert tc.css() == TOKENS["accent"]
    ansi = resolve("accent", "256")
    assert ansi.css() == f"ansi({ANSI256_FALLBACKS['accent']})"


def test_resolve_rejects_unknown_token_and_system():
    with pytest.raises(KeyError):
        resolve("banana")
    with pytest.raises(ValueError):
        resolve("accent", "16color")


def test_css_block_wires_every_token():
    block = theme.css_block()
    assert block.startswith(":root {")
    for name in TOKENS:
        assert f"--arcen-{name}:" in block


def test_font_stack_first_choice_is_fira_code():
    assert FONT_STACK[0] == "Fira Code"
    assert "monospace" in FONT_STACK  # ultimate fallback always present
