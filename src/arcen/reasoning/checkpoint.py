"""Checkpoints for long-horizon runs.

A loop that can run several passes and many tool calls needs a durable
record of where it was, or a crash turns a long operation into a mystery.
Each completed pass writes one JSON file atomically (temp + rename) under
``~/.arcen/checkpoints``; the newest file for a run is the resume point for
a human reading the failure, and the basis for a future automatic resume.

Checkpoints record *reasoning state*, not workspace state: the sandbox is
disposable by design, so a checkpoint never claims to restore files.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_DIR = "~/.arcen/checkpoints"
MAX_RUNS = 200  # bounded retention: reasoning state must not grow forever


@dataclass
class LoopCheckpoint:
    """One pass of one run, durable."""

    run_id: str
    goal: str
    pass_index: int
    action: str
    write_weight: float
    ok: bool
    confidence: float
    contradictions: list[str] = field(default_factory=list)
    termination: str | None = None
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


class CheckpointStore:
    """Writes and reads loop checkpoints. One directory, one file per pass."""

    def __init__(self, directory: str | Path = DEFAULT_DIR) -> None:
        self.directory = Path(directory).expanduser()

    def _ensure(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)

    def write(self, checkpoint: LoopCheckpoint) -> Path:
        """Atomically persist one checkpoint; returns the file path."""
        self._ensure()
        safe_run = "".join(c for c in checkpoint.run_id if c.isalnum() or c in "-_")[:64] or "run"
        path = self.directory / f"{safe_run}-{checkpoint.pass_index:03d}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(checkpoint.to_dict(), sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
        return path

    def read_run(self, run_id: str) -> list[dict]:
        """All checkpoints for a run, oldest pass first."""
        if not self.directory.is_dir():
            return []
        safe_run = "".join(c for c in run_id if c.isalnum() or c in "-_")[:64] or "run"
        out: list[dict] = []
        for path in sorted(self.directory.glob(f"{safe_run}-*.json")):
            try:
                out.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return out

    def prune(self, keep: int = MAX_RUNS) -> int:
        """Delete the oldest checkpoint files beyond ``keep``. Returns count."""
        if not self.directory.is_dir():
            return 0
        files = sorted(self.directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        removed = 0
        for path in files[keep:]:
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
        return removed
