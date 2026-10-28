"""TUI-01 — entry point selects between legacy and redesigned shells.

The redesign parks the shipped client in ``arcen.tui._legacy`` and keeps it
as the default behind ``arcen-tui`` until the TUI-18 cut-over. These tests
pin that behavior so later tickets cannot silently change the default.
"""

from __future__ import annotations

import pytest

pytest.importorskip("textual")

import arcen.tui as tui_pkg
import arcen.tui._legacy.app as legacy_app
import arcen.tui.app as new_app


def test_default_impl_is_legacy(monkeypatch):
    monkeypatch.delenv("ARCEN_TUI", raising=False)
    assert tui_pkg._selected_impl() == "legacy"


def test_unknown_impl_falls_back_to_legacy(monkeypatch):
    monkeypatch.setenv("ARCEN_TUI", "banana")
    assert tui_pkg._selected_impl() == "legacy"


def test_explicit_new_is_recognized(monkeypatch):
    monkeypatch.setenv("ARCEN_TUI", "NEW")  # case-insensitive
    assert tui_pkg._selected_impl() == "new"


def test_new_shell_routes_to_redesigned_app(monkeypatch):
    # TUI-04 onward: ARCEN_TUI=new launches arcen.tui.app with argv intact.
    monkeypatch.setenv("ARCEN_TUI", "new")
    called = {}

    def fake_run(argv):
        called["argv"] = argv
        return 0

    monkeypatch.setattr(new_app, "run", fake_run)
    assert tui_pkg.main(["--url", "http://x:3002"]) == 0
    assert called == {"argv": ["--url", "http://x:3002"]}


def test_demo_flag_wins_over_impl_flag(monkeypatch):
    # --demo routes before the legacy/new selection, regardless of ARCEN_TUI.
    monkeypatch.setenv("ARCEN_TUI", "new")
    called = {}

    def fake_run_demo(argv):
        called["argv"] = argv
        return 0

    import arcen.tui.demo as demo_mod

    monkeypatch.setattr(demo_mod, "run_demo", fake_run_demo)
    assert tui_pkg.main(["--demo"]) == 0
    assert called == {"argv": []}


def test_legacy_entry_resolves(monkeypatch):
    monkeypatch.delenv("ARCEN_TUI", raising=False)
    called = {}

    def fake_run(argv):
        called["argv"] = argv
        return 0

    # main() performs the from-import at call time, so the patched
    # attribute is what gets invoked.
    monkeypatch.setattr(legacy_app, "run", fake_run)
    assert tui_pkg.main(["--help-ish"]) == 0
    assert called == {"argv": ["--help-ish"]}
