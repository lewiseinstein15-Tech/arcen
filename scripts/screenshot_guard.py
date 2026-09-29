#!/usr/bin/env python3
"""ARCEN screenshot-harness staleness guard (T-048).

The v0.1.2 report caught the failure mode: ChatView's replay-of-history
fooled the harness into screenshotting a STALE answer — a stream that
looked finished but belonged to a previous turn. This module is the guard
that makes that impossible to regress:

  * a capture may only happen after the rendered message count has GROWN
    past the baseline taken before the turn was sent, AND
  * the wire must carry a FRESH terminal event (run.done / run.error)
    with a seq beyond the baseline — the current turn actually ended.

Either check failing raises StaleTurnError; the harness must refuse to
capture and exit non-zero with the reason. Pure logic, no playwright
imports — unit-tested by tests/test_screenshot_guard.py.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Iterable

TERMINAL_TYPES = ("run.done", "run.error")


class StaleTurnError(RuntimeError):
    """The harness refused to capture: the turn on screen is not fresh."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class TurnBaseline:
    """Snapshot taken BEFORE a turn is sent: how many messages were
    rendered and how far the wire had progressed."""

    rendered_count: int
    max_seq: int

    @classmethod
    def from_events(cls, rendered_count: int, events: Iterable[dict]) -> "TurnBaseline":
        seqs = [int(e["seq"]) for e in events if isinstance(e.get("seq"), int)]
        return cls(rendered_count=rendered_count, max_seq=max(seqs, default=0))


def assert_fresh_turn(
    baseline: TurnBaseline,
    rendered_count: int,
    wire_events: Iterable[dict],
) -> dict:
    """Guard a capture. Returns the fresh terminal event on success.

    Raises StaleTurnError when:
      * the rendered message count did not grow past the baseline, or
      * the wire shows no terminal event at all (the turn never fired), or
      * the only terminal event is a STALE one (seq within the baseline —
        a replay of history, not this turn's run.done).
    """
    events = list(wire_events)

    if rendered_count <= baseline.rendered_count:
        raise StaleTurnError(
            f"stale capture refused: rendered message count {rendered_count} "
            f"did not grow past baseline {baseline.rendered_count} — no new "
            f"turn is on screen (replayed history or the turn never rendered)"
        )

    terminals = [e for e in events if e.get("type") in TERMINAL_TYPES]
    if not terminals:
        raise StaleTurnError(
            f"stale capture refused: the wire shows no terminal event "
            f"(run.done/run.error) — the current turn never fired "
            f"({len(events)} events, baseline seq {baseline.max_seq})"
        )

    fresh = [e for e in terminals if int(e.get("seq", 0)) > baseline.max_seq]
    if not fresh:
        seqs = [int(e.get("seq", 0)) for e in terminals]
        raise StaleTurnError(
            f"stale capture refused: every terminal event on the wire "
            f"(seq {seqs}) belongs to the baseline window (<= {baseline.max_seq}) "
            f"— this is a replay of an old turn, not a fresh run.done"
        )

    return fresh[-1]


def fetch_session_events(base_url: str, session: str, timeout: float = 5.0) -> list[dict]:
    """Poll GET /api/sessions/<id>/events (the wire the guard reads)."""
    with urllib.request.urlopen(f"{base_url}/api/sessions/{session}/events", timeout=timeout) as r:
        return json.loads(r.read())
