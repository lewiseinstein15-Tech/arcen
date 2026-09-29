"""T-048 — the screenshot harness must refuse a stale capture.

Unit tests for scripts/screenshot_guard.py: the guard passes only when the
rendered message count grew past the baseline AND the wire carries a fresh
terminal event (seq beyond the baseline). Every refusal path raises
StaleTurnError with the reason — the harness exits non-zero on it.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / "scripts" / "screenshot_guard.py"

spec = importlib.util.spec_from_file_location("screenshot_guard", GUARD)
screenshot_guard = importlib.util.module_from_spec(spec)
sys.modules["screenshot_guard"] = screenshot_guard
spec.loader.exec_module(screenshot_guard)

assert_fresh_turn = screenshot_guard.assert_fresh_turn
TurnBaseline = screenshot_guard.TurnBaseline
StaleTurnError = screenshot_guard.StaleTurnError


def ev(seq: int, type_: str, **kw) -> dict:
    return {"seq": seq, "type": type_, **kw}


class TestFreshTurnPasses:
    def test_grown_count_and_fresh_run_done_pass(self):
        baseline = TurnBaseline(rendered_count=1, max_seq=2)
        wire = [ev(1, "run.start"), ev(2, "answer"), ev(3, "run.done", status="ok")]
        terminal = assert_fresh_turn(baseline, rendered_count=2, wire_events=wire)
        assert terminal["type"] == "run.done"
        assert terminal["seq"] == 3

    def test_run_error_is_a_valid_terminal_event(self):
        baseline = TurnBaseline(rendered_count=0, max_seq=0)
        wire = [ev(1, "run.start"), ev(2, "run.error", status="failed")]
        terminal = assert_fresh_turn(baseline, rendered_count=1, wire_events=wire)
        assert terminal["type"] == "run.error"

    def test_baseline_with_no_events_starts_at_zero(self):
        baseline = TurnBaseline.from_events(rendered_count=3, events=[])
        assert baseline.max_seq == 0
        assert_fresh_turn(baseline, rendered_count=4, wire_events=[ev(1, "run.done")])


class TestRefusesStaleCaptures:
    def test_count_not_grown_is_refused_even_with_fresh_done(self):
        baseline = TurnBaseline(rendered_count=2, max_seq=0)
        wire = [ev(1, "run.done", status="ok")]
        with pytest.raises(StaleTurnError) as exc:
            assert_fresh_turn(baseline, rendered_count=2, wire_events=wire)
        assert "did not grow past baseline" in exc.value.reason

    def test_no_terminal_event_is_refused(self):
        baseline = TurnBaseline(rendered_count=1, max_seq=1)
        wire = [ev(2, "run.start"), ev(3, "answer")]  # turn still running
        with pytest.raises(StaleTurnError) as exc:
            assert_fresh_turn(baseline, rendered_count=2, wire_events=wire)
        assert "no terminal event" in exc.value.reason

    def test_only_a_replayed_run_done_is_refused(self):
        # the v0.1.2 failure mode: history replay shows an OLD run.done
        baseline = TurnBaseline(rendered_count=1, max_seq=5)
        wire = [ev(3, "answer"), ev(5, "run.done", status="ok")]  # all <= baseline
        with pytest.raises(StaleTurnError) as exc:
            assert_fresh_turn(baseline, rendered_count=2, wire_events=wire)
        assert "replay of an old turn" in exc.value.reason

    def test_empty_wire_is_refused(self):
        baseline = TurnBaseline(rendered_count=0, max_seq=0)
        with pytest.raises(StaleTurnError) as exc:
            assert_fresh_turn(baseline, rendered_count=1, wire_events=[])
        assert "never fired" in exc.value.reason

    def test_refusal_carries_the_reason_for_the_nonzero_exit(self):
        baseline = TurnBaseline(rendered_count=7, max_seq=9)
        with pytest.raises(StaleTurnError) as exc:
            assert_fresh_turn(baseline, rendered_count=7, wire_events=[])
        assert exc.value.reason == str(exc.value)
