"""Single TUI entry point, optional dependency hint and demo precedence."""

from __future__ import annotations

import builtins
import sys

import pytest

pytest.importorskip("textual")
from arcen import tui
from arcen.tui import demo, live


def test_default_runs_live_with_arguments(monkeypatch):
    called = []
    monkeypatch.delenv("ARCEN_TUI", raising=False)
    monkeypatch.setattr(live, "run", lambda argv: called.append(argv) or 42)
    assert tui.main(["--url", "http://example"]) == 42
    assert called == [["--url", "http://example"]]


@pytest.mark.parametrize("old_flag", ["new", "legacy", "anything"])
def test_obsolete_env_flag_never_selects_another_app(monkeypatch, old_flag):
    monkeypatch.setenv("ARCEN_TUI", old_flag)
    monkeypatch.setattr(live, "run", lambda argv: 7)
    assert tui.main([]) == 7


def test_demo_precedes_live_and_preserves_options(monkeypatch):
    called = []
    monkeypatch.setattr(demo, "run_demo", lambda argv: called.append(argv) or 0)
    assert tui.main(["--demo", "--replay"]) == 0
    assert called == [["--replay"]]


def test_no_explicit_argv_uses_process_arguments(monkeypatch):
    called = []
    monkeypatch.setattr(sys, "argv", ["arcen-tui", "--no-serve"])
    monkeypatch.setattr(live, "run", lambda argv: called.append(argv) or 0)
    assert tui.main() == 0 and called == [["--no-serve"]]


def test_missing_textual_install_hint(monkeypatch):
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == "textual":
            raise ImportError("missing")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    with pytest.raises(SystemExit, match="arcen\\[tui\\]"):
        tui.main([])
