"""ARCEN — session store (BACKEND-SPEC Part 2 row 13 / ARCHITECTURE).

Pulled from Claude Code (history.jsonl format) — one append-only NDJSON
file per session, replayable forever.

Edited per the Pull Map: every line additionally carries ``seq`` and
``run_id``/``ts`` per the frozen event schema (Part 9). Write-once:
records are appended, never rewritten; a corrupt line is skipped and
counted, never fatal — a session dump must always replay.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from arcen.stream.events import from_dict


class SessionStore:
    """Append-only NDJSON persistence under ``~/.arcen/sessions``."""

    def __init__(self, directory: str | Path = "~/.arcen/sessions") -> None:
        self.directory = Path(directory).expanduser()
        os.makedirs(self.directory, exist_ok=True)

    # -- paths --------------------------------------------------------------
    def path(self, session_id: str) -> Path:
        return self.directory / f"{session_id}.jsonl"

    def exists(self, session_id: str) -> bool:
        return self.path(session_id).exists()

    # -- write ----------------------------------------------------------------
    def append(self, session_id: str, wire: dict) -> None:
        """Append one event as a single NDJSON line. Write-once, flush-immediate."""
        line = json.dumps(wire, ensure_ascii=False, separators=(",", ":"))
        with open(self.path(session_id), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    # -- read ---------------------------------------------------------------
    def read(self, session_id: str) -> list[dict]:
        """Replay every event, in file order. Corrupt lines are skipped."""
        events: list[dict] = []
        skipped = 0
        path = self.path(session_id)
        if not path.exists():
            return events
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    skipped += 1
        self._last_skipped = skipped
        return events

    def read_from(self, session_id: str, after_seq: int) -> list[dict]:
        """Events with seq > after_seq — the disk side of Last-Event-ID resume."""
        return [e for e in self.read(session_id) if e.get("seq", 0) > after_seq]

    def validate(self, session_id: str) -> tuple[int, int]:
        """Every line must parse AND satisfy the frozen schema.

        Returns (valid, invalid). The session file is a public artifact —
        a full dump is safe to share; a schema violation is a bug.
        """
        valid = invalid = 0
        for event in self.read(session_id):
            try:
                from_dict(event)
                valid += 1
            except Exception:  # noqa: BLE001 — counting, not raising
                invalid += 1
        return valid, invalid

    # -- listing --------------------------------------------------------------
    def list(self) -> list[dict]:
        """One row per session file, oldest first."""
        rows = []
        for path in sorted(self.directory.glob("*.jsonl")):
            rows.append(
                {
                    "id": path.stem,
                    "events": sum(1 for line in open(path, "r", encoding="utf-8") if line.strip()),
                    "bytes": path.stat().st_size,
                    "modified": path.stat().st_mtime,
                }
            )
        return rows
