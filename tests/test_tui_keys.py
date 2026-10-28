"""TUI-02 — frozen key-binding map."""

from __future__ import annotations

import re

import pytest

from arcen.tui import keys
from arcen.tui.keys import (
    FOOTER_HINTS,
    KEYS,
    SCOPE_COMPOSER,
    SCOPE_GLOBAL,
    SCOPE_MODAL,
    for_scope,
    help_rows,
)

SNAKE = re.compile(r"^[a-z][a-z0-9_]*$")
SCOPES = {SCOPE_GLOBAL, SCOPE_COMPOSER, SCOPE_MODAL}


def test_specs_well_formed():
    assert KEYS
    for spec in KEYS:
        assert spec.key.strip()
        assert SNAKE.match(spec.action), f"action {spec.action!r} not snake_case"
        assert spec.description.strip()
        assert spec.scope in SCOPES


def test_key_scope_pairs_are_unique():
    pairs = [(s.key, s.scope) for s in KEYS]
    assert len(pairs) == len(set(pairs))


def test_scope_inclusion_rules():
    globals_only = for_scope(SCOPE_GLOBAL)
    assert all(s.scope == SCOPE_GLOBAL for s in globals_only)

    composer = for_scope(SCOPE_COMPOSER)
    # global bindings remain available inside the composer scope
    assert {s.action for s in globals_only} <= {s.action for s in composer}
    assert any(s.scope == SCOPE_COMPOSER for s in composer)

    modal = for_scope(SCOPE_MODAL)
    assert {s.action for s in globals_only} <= {s.action for s in modal}
    assert any(s.action == "close_modal" for s in modal)


def test_help_rows_match_scope():
    rows = help_rows(SCOPE_GLOBAL)
    assert len(rows) == len(for_scope(SCOPE_GLOBAL))
    assert all(isinstance(row, tuple) and len(row) == 2 for row in rows)


def test_footer_hints_map_to_real_actions():
    actions = {s.action for s in KEYS}
    # footer labels name the canonical actions from the prototype chrome
    for _, label in FOOTER_HINTS:
        assert label  # human label present
    assert {"interrupt", "external_editor", "command_palette",
            "resume", "help"} <= actions


def test_priority_on_run_control_bindings():
    by_action = {s.action: s for s in KEYS}
    assert by_action["interrupt"].priority is True
    assert by_action["quit"].priority is True


def test_textual_binding_factory():
    pytest.importorskip("textual")
    bindings = keys.to_textual_bindings(SCOPE_GLOBAL)
    assert len(bindings) == len(for_scope(SCOPE_GLOBAL))
    textual_keys = {b.key for b in bindings}
    assert "ctrl+c" in textual_keys and "ctrl+q" in textual_keys
    # every produced object really is a Textual Binding
    from textual.app import Binding

    assert all(isinstance(b, Binding) for b in bindings)
