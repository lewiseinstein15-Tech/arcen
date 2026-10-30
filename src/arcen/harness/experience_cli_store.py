"""Dedicated CLI experience database with cooperating-process file locking.

This does not lock direct Python MemoryStore callers or defend against hostile
local filesystem mutation. The separate database is never included in prompts.
"""

from __future__ import annotations

import os
import sqlite3
import stat
from contextlib import closing, contextmanager

from arcen.memory.store import MemoryStore

from .experience import ExperienceLibrary
from .resolver import HarnessError
from .review import ReviewLedger
from .store import HarnessStore

_APPLICATION_ID = 0x41524345
_VERSION = 1
_OBJECTS = {
    ("table", "entities"),
    ("table", "relations"),
    ("table", "facts"),
    ("index", "idx_relations_src"),
    ("index", "idx_relations_dst"),
    ("index", "idx_facts_entity"),
    ("index", "idx_facts_key"),
}
_COLUMNS = {
    "entities": [("name", "TEXT"), ("kind", "TEXT"), ("first_seen", "REAL"), ("last_seen", "REAL")],
    "relations": [
        ("id", "INTEGER"),
        ("src", "TEXT"),
        ("dst", "TEXT"),
        ("kind", "TEXT"),
        ("created_at", "REAL"),
    ],
    "facts": [
        ("id", "INTEGER"),
        ("entity", "TEXT"),
        ("key", "TEXT"),
        ("fact", "TEXT"),
        ("weight", "REAL"),
        ("sources", "TEXT"),
        ("created_at", "REAL"),
        ("last_accessed", "REAL"),
        ("valid_from", "REAL"),
        ("invalid_at", "REAL"),
        ("archived", "INTEGER"),
    ],
}


def _regular(path) -> bool:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(mode):
        raise HarnessError("experience database must be a regular file")
    return True


def _validate(db: sqlite3.Connection) -> None:
    if (
        db.execute("PRAGMA application_id").fetchone()[0] != _APPLICATION_ID
        or db.execute("PRAGMA user_version").fetchone()[0] != _VERSION
    ):
        raise HarnessError("invalid experience database identity")
    objects = {
        tuple(row)
        for row in db.execute("SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")
    }
    if objects != _OBJECTS:
        raise HarnessError("invalid experience database schema")
    for table, expected in _COLUMNS.items():
        if [(row[1], row[2]) for row in db.execute(f"PRAGMA table_info({table})")] != expected:
            raise HarnessError("invalid experience database schema")


@contextmanager
def open_cli_experience(store: HarnessStore, reviews: ReviewLedger, *, create: bool = False):
    """Open a private database while holding a nonblocking cooperative lock."""
    if (
        type(store) is not HarnessStore
        or type(reviews) is not ReviewLedger
        or reviews.store is not store
        or type(create) is not bool
    ):
        raise HarnessError("invalid experience dependencies")
    try:
        import fcntl
    except ImportError:
        raise HarnessError("experience CLI requires filesystem locking support") from None
    store._path("0" * 64)
    path = store.root / "experience.sqlite3"
    lock_path = store.root / "experience.lock"
    if not create and not _regular(path):
        raise HarnessError("experience database is missing")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(lock_path, flags, 0o600)
    except OSError:
        raise HarnessError("cannot open experience lock") from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise HarnessError("experience lock must be a regular file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise HarnessError("experience database is busy; retry later") from None
        existed = _regular(path)
        if not existed:
            if not create:
                raise HarnessError("experience database is missing")
            try:
                new_fd = os.open(
                    path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600
                )
            except OSError:
                raise HarnessError("cannot create experience database") from None
            os.close(new_fd)
        if existed:
            # Validate before MemoryStore's schema-creating constructor.
            with closing(
                sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True, timeout=10)
            ) as check:
                _validate(check)
        memory = MemoryStore(str(path))
        try:
            if not existed:
                memory.conn.execute(f"PRAGMA application_id={_APPLICATION_ID}")
                memory.conn.execute(f"PRAGMA user_version={_VERSION}")
                memory.conn.commit()
            _validate(memory.conn)
            yield ExperienceLibrary(memory, reviews)
        finally:
            memory.close()
    finally:
        os.close(fd)  # releases flock, including on failure and interruption
