"""SQLite-backed shared admission counters; not token/USD or runtime limits.

Only calls explicitly using this trusted local budget ID are counted. A stop
prevents later admissions, not work already admitted. This is not a scheduler.
"""

from __future__ import annotations

import math
import os
import re
import secrets
import sqlite3
import stat
import time
from contextlib import contextmanager
from dataclasses import dataclass

from .budget import BudgetExhausted, BudgetSnapshot
from .resolver import HarnessError
from .store import HarnessStore

_ID = re.compile(r"[0-9a-f]{32}\Z")
_REASONS = frozenset(
    {
        "stopped",
        "deadline reached",
        "clock rollback",
        "trials limit reached",
        "model_calls limit reached",
        "judge_calls limit reached",
    }
)


@dataclass(frozen=True, slots=True)
class DurableBudgetSnapshot(BudgetSnapshot):
    """An atomic snapshot of durable limits and admissions, not a reservation."""

    max_trials: int
    max_model_calls: int
    max_judge_calls: int
    admission_seconds_remaining: float


class DurableBudget:
    """Durable atomic reservations shared by cooperating local processes."""

    def __init__(self, store: HarnessStore, identifier: str):
        if (
            type(store) is not HarnessStore
            or type(identifier) is not str
            or not _ID.fullmatch(identifier)
        ):
            raise HarnessError("invalid durable budget identity")
        self.store, self.id = store, identifier
        self.path = store.root / "budgets.sqlite3"
        self._prepare(create=False)
        self.snapshot()

    @classmethod
    def create(
        cls,
        store: HarnessStore,
        *,
        max_trials: int,
        max_model_calls: int,
        max_judge_calls: int,
        admission_seconds: float,
    ) -> DurableBudget:
        if (
            type(store) is not HarnessStore
            or any(
                type(x) is not int or not 0 <= x <= 100000
                for x in (max_trials, max_model_calls, max_judge_calls)
            )
            or max_trials < 1
            or type(admission_seconds) not in (int, float)
            or not math.isfinite(admission_seconds)
            or not 0.1 <= admission_seconds <= 86400
        ):
            raise HarnessError("invalid durable budget limits")
        obj = cls.__new__(cls)
        obj.store, obj.id, obj.path = store, secrets.token_hex(16), store.root / "budgets.sqlite3"
        obj._prepare(create=True)
        now = time.time()
        if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
            raise HarnessError("invalid budget clock")
        with obj._connect() as db:
            db.execute(
                "INSERT INTO budgets VALUES (?,?,?,?,0,0,0,?,?,?,NULL)",
                (
                    obj.id,
                    max_trials,
                    max_model_calls,
                    max_judge_calls,
                    now,
                    now,
                    now + admission_seconds,
                ),
            )
        obj.snapshot()
        return obj

    def _prepare(self, *, create: bool) -> None:
        self.store._path("0" * 64)
        if create:
            try:
                fd = os.open(
                    self.path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
            except FileExistsError:
                if not stat.S_ISREG(self.path.lstat().st_mode):
                    raise HarnessError("budget database must be a regular file")
            except OSError:
                raise HarnessError("cannot create budget database") from None
            else:
                os.close(fd)
        elif self.path.is_symlink() or not self.path.is_file():
            raise HarnessError("budget database is missing or invalid")
        with self._connect(read_only=not create) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in ((0, 1) if create else (1,)):
                raise HarnessError("unsupported budget database schema")
            if version == 0:
                if (
                    not create
                    or db.execute(
                        "SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1"
                    ).fetchone()
                ):
                    raise HarnessError("invalid budget database schema")
                db.executescript("""
                    CREATE TABLE budgets (
                        id TEXT PRIMARY KEY NOT NULL,
                        max_trials INTEGER NOT NULL, max_model_calls INTEGER NOT NULL,
                        max_judge_calls INTEGER NOT NULL,
                        trials INTEGER NOT NULL, model_calls INTEGER NOT NULL,
                        judge_calls INTEGER NOT NULL,
                        created REAL NOT NULL, last_seen REAL NOT NULL,
                        deadline REAL NOT NULL, reason TEXT
                    );
                    PRAGMA user_version=1;
                """)
            objects = set(
                db.execute(
                    "SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                ).fetchall()
            )
            rows = db.execute("PRAGMA table_info(budgets)").fetchall()
            expected = [
                ("id", "TEXT", 1, 1),
                ("max_trials", "INTEGER", 1, 0),
                ("max_model_calls", "INTEGER", 1, 0),
                ("max_judge_calls", "INTEGER", 1, 0),
                ("trials", "INTEGER", 1, 0),
                ("model_calls", "INTEGER", 1, 0),
                ("judge_calls", "INTEGER", 1, 0),
                ("created", "REAL", 1, 0),
                ("last_seen", "REAL", 1, 0),
                ("deadline", "REAL", 1, 0),
                ("reason", "TEXT", 0, 0),
            ]
            if (
                objects != {("table", "budgets")}
                or [(r[1], r[2], r[3], r[5]) for r in rows] != expected
                or any(r[4] is not None for r in rows)
            ):
                raise HarnessError("invalid budget database schema")

    @contextmanager
    def _connect(self, *, read_only: bool = False):
        self.store._path("0" * 64)
        if self.path.is_symlink() or not self.path.is_file():
            raise HarnessError("budget database is missing or invalid")
        try:
            db = sqlite3.connect(
                self.path.absolute().as_uri() + ("?mode=ro" if read_only else "?mode=rw"),
                timeout=10,
                uri=True,
            )
        except sqlite3.Error:
            raise HarnessError("cannot open budget database") from None
        try:
            with db:
                yield db
        finally:
            db.close()

    def _update(self, operation: str) -> DurableBudgetSnapshot:
        if operation not in {
            "snapshot",
            "checkpoint",
            "trials",
            "model_calls",
            "judge_calls",
            "stop",
        }:
            raise HarnessError("invalid budget operation")
        blocked = False
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT max_trials,max_model_calls,max_judge_calls,trials,model_calls,judge_calls,created,last_seen,deadline,reason FROM budgets WHERE id=?",
                (self.id,),
            ).fetchone()
            if row is None:
                raise HarnessError("unknown durable budget")
            limits, used, created, last, deadline, reason = (
                row[:3],
                list(row[3:6]),
                row[6],
                row[7],
                row[8],
                row[9],
            )
            if (
                any(type(x) is not int or not 0 <= x <= 100000 for x in (*limits, *used))
                or limits[0] < 1
                or any(x > limit for x, limit in zip(used, limits, strict=True))
                or any(
                    type(x) not in (int, float) or not math.isfinite(x) or x < 0
                    for x in (created, last, deadline)
                )
                or not created <= last <= deadline
                or deadline - created > 86400.00001
                or (reason is not None and (type(reason) is not str or reason not in _REASONS))
            ):
                raise HarnessError("invalid durable budget record")
            now = time.time()
            if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
                raise HarnessError("invalid budget clock")
            if reason is None:
                if now < last:
                    reason = "clock rollback"
                elif now >= deadline:
                    reason = "deadline reached"
                elif operation == "stop":
                    reason = "stopped"
                elif operation in {"trials", "model_calls", "judge_calls"}:
                    index = ("trials", "model_calls", "judge_calls").index(operation)
                    if used[index] >= limits[index]:
                        reason = operation + " limit reached"
                    else:
                        used[index] += 1
            blocked = reason is not None and operation not in {"snapshot", "stop"}
            # last_seen never exceeds the deadline, preserving record invariants.
            last = min(deadline, max(last, now))
            db.execute(
                "UPDATE budgets SET trials=?,model_calls=?,judge_calls=?,last_seen=?,reason=? WHERE id=?",
                (*used, last, reason, self.id),
            )
            snapshot = DurableBudgetSnapshot(
                *used,
                reason is not None,
                reason,
                max(0.0, now - created),
                *limits,
                max(0.0, deadline - now) if reason is None else 0.0,
            )
        if blocked:
            raise BudgetExhausted("durable budget closed: " + reason)
        return snapshot

    def checkpoint(self) -> None:
        self._update("checkpoint")

    def reserve_trial(self) -> None:
        self._update("trials")

    def reserve_model_call(self) -> None:
        self._update("model_calls")

    def reserve_judge_call(self) -> None:
        self._update("judge_calls")

    def stop(self) -> None:
        self._update("stop")

    def snapshot(self) -> DurableBudgetSnapshot:
        return self._update("snapshot")
