"""ARCEN — NDJSON streaming emitter (BACKEND-SPEC Part 9).

Pulled from AG-UI (sdk/python/ag_ui/) — the typed event stream encoder.

Edited per the Pull Map: reduced to the frozen 17 events, NDJSON framing.

Contract:
- one JSON object per line, terminated \\n, UTF-8, compact separators;
- every event carries ``seq`` (monotonic per session, starts at 1) and
  ``ts`` (Unix epoch seconds, float);
- the emitter buffers what it sent so a reconnecting client can replay
  from ``Last-Event-ID`` — ``replay(after_seq)`` returns seq > after_seq;
- live subscribers (the HTTP stream handler) are notified on every emit.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from .events import Event, to_dict, to_line


class StreamEmitter:
    """Stamps seq + ts, frames NDJSON, buffers for replay, notifies subs."""

    def __init__(self, session_id: str, keep_last: int = 100_000) -> None:
        self.session_id = session_id
        self.keep_last = keep_last
        self._seq = 0
        self._buffer: list[dict] = []
        self._subs: list[Callable[[dict], None]] = []
        self._lock = threading.Lock()

    @property
    def last_seq(self) -> int:
        with self._lock:
            return self._seq

    def subscribe(self, fn: Callable[[dict], None]) -> None:
        """Register a live listener. Receives every event from now on."""
        with self._lock:
            self._subs.append(fn)

    def emit(self, event: Event) -> dict:
        """Stamp, buffer, notify. Returns the canonical wire dict."""
        with self._lock:
            self._seq += 1
            event.seq = self._seq
            event.ts = event.ts or time.time()
            wire = to_dict(event)
            self._buffer.append(wire)
            if len(self._buffer) > self.keep_last:
                del self._buffer[: len(self._buffer) - self.keep_last]
            subs = list(self._subs)
        for fn in subs:
            fn(wire)
        return wire

    def line(self, event: Event) -> str:
        """Emit and return the NDJSON line — convenience for CLI demos."""
        return to_line(event) if event.seq else self.to_line(self.emit(event))

    def to_line(self, wire: dict) -> str:
        import json

        return json.dumps(wire, ensure_ascii=False, separators=(",", ":"))

    def replay(self, after_seq: int) -> list[dict]:
        """Buffered events with seq > after_seq (the Last-Event-ID resume)."""
        with self._lock:
            return [e for e in self._buffer if e["seq"] > after_seq]

    def replay_lines(self, after_seq: int) -> list[str]:
        return [self.to_line(e) + "\n" for e in self.replay(after_seq)]

    def all_lines(self) -> list[str]:
        """The full session so far, one NDJSON line per event."""
        with self._lock:
            return [self.to_line(e) + "\n" for e in self._buffer]
