"""Locally curated, content-addressed tasks; never execute or adopt anything.

Tasks are stored as plaintext. Hashes and local names do not authenticate origin,
filter all secrets, or make instructions safe. The store and SQLite are trusted.
"""

from __future__ import annotations

import math
import os
import re
import sqlite3
import stat
import time
from contextlib import contextmanager
from dataclasses import dataclass

from arcen.plugins.redact_secrets import redact_text

from .model import content_hash
from .resolver import HarnessError
from .store import HarnessStore

_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
_HASH = re.compile(r"[a-f0-9]{64}\Z")
MAX_TASKS = 1000
MAX_TASK_CHARS = 4000
MAX_TASK_BYTES = 16000


@dataclass(frozen=True, slots=True)
class TaskEntry:
    name: str
    digest: str
    created_at: int


def validate_name(name: str) -> None:
    if type(name) is not str or not _NAME.fullmatch(name):
        raise HarnessError("invalid task name")


def validate_task(text: str) -> bytes:
    """Validate bounded exact text; known-secret matching is best effort."""
    if type(text) is not str or not text.strip() or len(text) > MAX_TASK_CHARS:
        raise HarnessError("invalid task text")
    try:
        raw = text.encode("utf-8")
    except UnicodeError:
        raise HarnessError("task must be UTF-8") from None
    if len(raw) > MAX_TASK_BYTES:
        raise HarnessError("task exceeds size limit")
    if redact_text(text) != text:
        raise HarnessError("task contains a detected secret")
    return raw


class TaskBank:
    """Immutable task names and verified blobs in a trusted local store."""

    def __init__(self, store: HarnessStore, *, create: bool = False):
        if type(store) is not HarnessStore or type(create) is not bool:
            raise HarnessError("invalid task bank settings")
        self.store = store
        self.path = store.root / "tasks.sqlite3"
        store._path("0" * 64)
        if create:
            try:
                fd = os.open(
                    self.path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
            except FileExistsError:
                if not stat.S_ISREG(self.path.lstat().st_mode):
                    raise HarnessError("task database must be a regular file")
            except OSError:
                raise HarnessError("cannot create task database") from None
            else:
                os.close(fd)
        elif self.path.is_symlink() or not self.path.is_file():
            raise HarnessError("task bank is missing or invalid")
        with self._connect(read_only=not create) as db:
            if create:
                db.execute("BEGIN IMMEDIATE")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in ((0, 1) if create else (1,)):
                raise HarnessError("unsupported task database schema")
            if version == 0:
                if (
                    not create
                    or db.execute(
                        "SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1"
                    ).fetchone()
                ):
                    raise HarnessError("invalid task database schema")
                db.execute(
                    "CREATE TABLE tasks (name TEXT PRIMARY KEY NOT NULL, digest TEXT NOT NULL, created_at INTEGER NOT NULL)"
                )
                db.execute("PRAGMA user_version=1")
            objects = set(
                db.execute(
                    "SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                ).fetchall()
            )
            rows = db.execute("PRAGMA table_info(tasks)").fetchall()
            indexes = {
                (r[3], tuple(x[2] for x in db.execute(f"PRAGMA index_info('{r[1]}')")))
                for r in db.execute("PRAGMA index_list(tasks)")
                if r[2] == 1 and r[4] == 0
            }
            if (
                objects != {("table", "tasks")}
                or [(r[1], r[2], r[3], r[5]) for r in rows]
                != [
                    ("name", "TEXT", 1, 1),
                    ("digest", "TEXT", 1, 0),
                    ("created_at", "INTEGER", 1, 0),
                ]
                or any(r[4] is not None for r in rows)
                or indexes != {("pk", ("name",))}
            ):
                raise HarnessError("invalid task database schema")

    @contextmanager
    def _connect(self, *, read_only: bool = False):
        self.store._path("0" * 64)
        if self.path.is_symlink() or not self.path.is_file():
            raise HarnessError("task database is missing or invalid")
        try:
            db = sqlite3.connect(
                self.path.absolute().as_uri() + ("?mode=ro" if read_only else "?mode=rw"),
                timeout=10,
                uri=True,
            )
        except sqlite3.Error:
            raise HarnessError("cannot open task database") from None
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _entry(row) -> TaskEntry:
        if (
            len(row) != 3
            or type(row[0]) is not str
            or not _NAME.fullmatch(row[0])
            or type(row[1]) is not str
            or not _HASH.fullmatch(row[1])
            or type(row[2]) is not int
            or row[2] < 0
        ):
            raise HarnessError("invalid task bank record")
        return TaskEntry(*row)

    def add(self, name: str, text: str) -> TaskEntry:
        validate_name(name)
        raw = validate_task(text)
        digest = content_hash(raw)
        clock = time.time()
        if type(clock) not in (int, float) or not math.isfinite(clock) or clock < 0:
            raise HarnessError("invalid task clock")
        now = int(clock)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT name,digest,created_at FROM tasks WHERE name=?", (name,)
            ).fetchone()
            if existing is not None:
                entry = self._entry(existing)
                if entry.digest != digest:
                    raise HarnessError("task name already exists with different content")
                # Validate the object even for an idempotent import.
                if self.store.get_blob(digest) != raw:
                    raise HarnessError("task object integrity failure")
                return entry
            if db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] >= MAX_TASKS:
                raise HarnessError("task bank limit reached")
            if self.store.put_blob(raw) != digest:
                raise HarnessError("task object integrity failure")
            db.execute("INSERT INTO tasks VALUES (?,?,?)", (name, digest, now))
        return TaskEntry(name, digest, now)

    def read(self, digest: str) -> str:
        if type(digest) is not str or not _HASH.fullmatch(digest):
            raise HarnessError("invalid task identifier")
        with self._connect(read_only=True) as db:
            row = db.execute(
                "SELECT name,digest,created_at FROM tasks WHERE digest=? ORDER BY name LIMIT 1",
                (digest,),
            ).fetchone()
        if row is None:
            raise HarnessError("unknown task")
        self._entry(row)
        try:
            text = self.store.get_blob(digest).decode("utf-8")
        except UnicodeError:
            raise HarnessError("invalid task object") from None
        validate_task(text)
        return text

    def list(self) -> tuple[TaskEntry, ...]:
        with self._connect(read_only=True) as db:
            rows = db.execute(
                "SELECT name,digest,created_at FROM tasks ORDER BY name LIMIT ?", (MAX_TASKS + 1,)
            ).fetchall()
        if len(rows) > MAX_TASKS:
            raise HarnessError("task bank limit exceeded")
        entries = tuple(self._entry(row) for row in rows)
        for entry in entries:
            self.read(entry.digest)
        return entries
