"""Opt-in durable trial slots for cooperating local processes.

Not an isolation boundary, scheduler, lease, or crash recovery system. A
crashed process can leave a slot occupied forever; it is never auto-reclaimed.
Local files and all participants are trusted not to bypass or modify this API.
"""

from __future__ import annotations

import os
import re
import secrets
import sqlite3
import stat
from contextlib import contextmanager, suppress
from dataclasses import dataclass

from .budget import TrialConcurrencyFull
from .durable_budget import DurableBudget
from .resolver import HarnessError
from .store import HarnessStore

_APPLICATION_ID = 0x4152534C
_VERSION = 1
_TOKEN = re.compile(r"[0-9a-f]{32}\Z")
_OBJECTS = {("table", "limits"), ("table", "slots")}
_COLUMNS = {
    "limits": [("budget_id", "TEXT", 1, 1), ("max_active", "INTEGER", 1, 0)],
    "slots": [("token", "TEXT", 1, 1), ("budget_id", "TEXT", 1, 0)],
}


@dataclass(frozen=True, slots=True)
class DurableSlotSnapshot:
    budget_id: str
    max_active: int
    occupied: int


class DurableTrialSlots:
    """A persisted concurrency cap tied to one durable budget ID.

    Every process must use the same store, budget ID and slot API. A slot is
    retained if the body raises or the process dies; on a caught error the
    durable budget is stopped on a best-effort basis. Stopping can fail if the
    budget database is unavailable. There is deliberately no reset/reclaim API.
    """

    def __init__(self, budget: DurableBudget):
        self._set_budget(budget)
        self._prepare(create=False)
        self.snapshot()

    def _set_budget(self, budget: DurableBudget) -> None:
        if type(budget) is not DurableBudget:
            raise HarnessError("durable trial slots require a durable budget")
        budget.store._path("0" * 64)
        self.budget = budget
        self.path = budget.store.root / "trial_slots.sqlite3"

    @classmethod
    def create(cls, budget: DurableBudget, *, max_active: int) -> DurableTrialSlots:
        if type(max_active) is not int or not 1 <= max_active <= 100000:
            raise HarnessError("invalid durable trial concurrency limit")
        obj = cls.__new__(cls)
        obj._set_budget(budget)
        budget.checkpoint()
        obj._prepare(create=True)
        with obj._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            obj._validate(db)
            if db.execute("SELECT 1 FROM limits WHERE budget_id=?", (budget.id,)).fetchone():
                raise HarnessError("durable trial concurrency already configured")
            db.execute("INSERT INTO limits VALUES (?,?)", (budget.id, max_active))
        obj.snapshot()
        return obj

    @classmethod
    def validate_database_schema(cls, store: HarnessStore) -> None:
        if type(store) is not HarnessStore:
            raise HarnessError("invalid durable trial slot store")
        store._path("0" * 64)
        obj = cls.__new__(cls)
        obj.path = store.root / "trial_slots.sqlite3"
        obj._prepare(create=False)

    def _prepare(self, *, create: bool) -> None:
        new_file = False
        if create:
            try:
                fd = os.open(
                    self.path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
            except FileExistsError:
                pass
            except OSError:
                raise HarnessError("cannot create durable trial slot database") from None
            else:
                os.close(fd)
                new_file = True
        with self._connect(read_only=not create) as db:
            db.execute("BEGIN IMMEDIATE" if create else "BEGIN")
            objects = set(
                db.execute(
                    "SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                ).fetchall()
            )
            version = db.execute("PRAGMA user_version").fetchone()[0]
            app_id = db.execute("PRAGMA application_id").fetchone()[0]
            if new_file and version == 0 and app_id == 0 and not objects:
                db.execute(
                    "CREATE TABLE limits (budget_id TEXT PRIMARY KEY NOT NULL, max_active INTEGER NOT NULL)"
                )
                db.execute(
                    "CREATE TABLE slots (token TEXT PRIMARY KEY NOT NULL, budget_id TEXT NOT NULL)"
                )
                db.execute(f"PRAGMA application_id={_APPLICATION_ID}")
                db.execute(f"PRAGMA user_version={_VERSION}")
            self._validate(db)

    @contextmanager
    def _connect(self, *, read_only: bool = False):
        try:
            mode = self.path.lstat().st_mode
            if not stat.S_ISREG(mode):
                raise HarnessError("durable trial slot database must be a regular file")
            db = sqlite3.connect(
                self.path.absolute().as_uri() + ("?mode=ro" if read_only else "?mode=rw"),
                timeout=10,
                uri=True,
            )
            try:
                with db:
                    yield db
            finally:
                db.close()
        except (sqlite3.Error, OSError):
            raise HarnessError("durable trial slot database unavailable") from None

    @staticmethod
    def _validate(db: sqlite3.Connection) -> None:
        if (
            db.execute("PRAGMA application_id").fetchone()[0] != _APPLICATION_ID
            or db.execute("PRAGMA user_version").fetchone()[0] != _VERSION
            or set(
                db.execute(
                    "SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                ).fetchall()
            )
            != _OBJECTS
        ):
            raise HarnessError("invalid durable trial slot schema")
        for table, expected in _COLUMNS.items():
            rows = db.execute(f"PRAGMA table_info({table})").fetchall()
            if [(r[1], r[2], r[3], r[5]) for r in rows] != expected or any(
                r[4] is not None for r in rows
            ):
                raise HarnessError("invalid durable trial slot schema")

    def _state(self, db: sqlite3.Connection) -> DurableSlotSnapshot:
        row = db.execute(
            "SELECT max_active FROM limits WHERE budget_id=?", (self.budget.id,)
        ).fetchone()
        if row is None:
            raise HarnessError("durable trial concurrency not configured")
        limit = row[0]
        if type(limit) is not int or not 1 <= limit <= 100000:
            raise HarnessError("invalid durable trial concurrency record")
        rows = db.execute(
            "SELECT token FROM slots WHERE budget_id=? LIMIT 100001", (self.budget.id,)
        ).fetchall()
        if len(rows) > limit or any(
            type(r[0]) is not str or not _TOKEN.fullmatch(r[0]) for r in rows
        ):
            raise HarnessError("invalid durable trial slot records")
        return DurableSlotSnapshot(self.budget.id, limit, len(rows))

    def snapshot(self) -> DurableSlotSnapshot:
        with self._connect(read_only=True) as db:
            db.execute("BEGIN")
            self._validate(db)
            return self._state(db)

    def _release(self, token: str) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._validate(db)
            self._state(db)
            cur = db.execute(
                "DELETE FROM slots WHERE token=? AND budget_id=?", (token, self.budget.id)
            )
            if cur.rowcount != 1:
                raise HarnessError("durable trial slot missing")

    @contextmanager
    def trial_slot(self):
        """Acquire without waiting for capacity; retain on any uncertain failure."""
        self.budget.checkpoint()
        token = secrets.token_hex(16)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._validate(db)
            state = self._state(db)
            if state.occupied >= state.max_active:
                raise TrialConcurrencyFull("durable budget trial concurrency full")
            db.execute("INSERT INTO slots VALUES (?,?)", (token, self.budget.id))
        try:
            # A stop may race with acquisition. No work has started yet.
            self.budget.checkpoint()
        except BaseException:
            try:
                self._release(token)
            except BaseException:
                with suppress(Exception):
                    self.budget.stop()
                raise
            raise
        try:
            yield
        except BaseException:
            with suppress(Exception):  # the original failure and retained slot remain authoritative
                self.budget.stop()
            raise
        else:
            try:
                self._release(token)
            except BaseException:
                with suppress(Exception):  # failed release remains an uncertain occupied slot
                    self.budget.stop()
                raise
