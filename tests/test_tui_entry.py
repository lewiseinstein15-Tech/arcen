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


def test_default_impl_is_legacy(monkeypatch):
    monkeypatch.delenv("ARCEN_TUI", raising=False)
    assert tui_pkg._selected_impl() == "legacy"


def test_unknown_impl_falls_back_to_legacy(monkeypatch):
    monkeypatch.setenv("ARCEN_TUI", "banana")
    assert tui_pkg._selected_impl() == "legacy"


def test_explicit_new_is_recognized(monkeypatch):
    monkeypatch.setenv("ARCEN_TUI", "NEW")  # case-insensitive
    assert tui_pkg._selected_impl() == "new"


def test_new_shell_unavailable_before_tui04(monkeypatch):
    # arcen.tui.app does not exist until the shell ticket lands.
    monkeypatch.setenv("ARCEN_TUI", "new")
    with pytest.raises(SystemExit, match="redesigned shell is not built"):
        tui_pkg.main([])


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
