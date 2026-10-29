"""Transactional local harness refs and append-only lineage, not an adoption gate.

This API records metadata only. No current run selects or executes a stored ref,
and the adopted baseline cannot be moved until the future policy/approval gate.
The store directory is trusted local state, not a security boundary against a
hostile process that can alter SQLite files or object paths.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
from contextlib import contextmanager
from dataclasses import dataclass

from .manifest import default_manifest
from .model import canonical_manifest, content_hash
from .resolver import HarnessError
from .store import HarnessStore

_CANDIDATE = re.compile(r"refs/candidates/[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}\Z")
_ADOPTED = "refs/heads/adopted"
_DECISIONS = frozenset({"proposed", "rejected", "observed"})


@dataclass(frozen=True, slots=True)
class LineageEdge:
    child: str
    parent: str
    task: str
    trajectory_ids: tuple[str, ...]
    judge_report: str
    decision: str


class HarnessLineage:
    """SQLite lineage and refs over a separately verified object store."""

    def __init__(self, store: HarnessStore):
        self.store = store
        self.path = store.root / "lineage.sqlite3"
        self._prepare_file()
        with self._connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise HarnessError("unsupported lineage schema")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT PRIMARY KEY NOT NULL
                );
                CREATE TABLE IF NOT EXISTS edges (
                    child TEXT NOT NULL REFERENCES nodes(id),
                    parent TEXT NOT NULL REFERENCES nodes(id),
                    task TEXT NOT NULL,
                    trajectories TEXT NOT NULL,
                    judge_report TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    PRIMARY KEY(child, parent),
                    CHECK(child != parent)
                );
                CREATE TABLE IF NOT EXISTS refs (
                    name TEXT PRIMARY KEY NOT NULL,
                    node TEXT NOT NULL REFERENCES nodes(id)
                );
                CREATE TABLE IF NOT EXISTS ref_history (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    old_node TEXT,
                    new_node TEXT NOT NULL REFERENCES nodes(id)
                );
                PRAGMA user_version = 1;
            """)

    def _prepare_file(self) -> None:
        try:
            fd = os.open(
                self.path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
        except FileExistsError:
            if not stat.S_ISREG(self.path.lstat().st_mode):
                raise HarnessError("lineage database must be a regular file")
        except OSError as exc:
            raise HarnessError("cannot create lineage database") from exc
        else:
            os.close(fd)

    @contextmanager
    def _connect(self):
        # Reject obvious symlink substitution; hostile concurrent mutation of
        # the trusted parent hierarchy is outside this local API's boundary.
        self.store._path("0" * 64)
        if self.path.is_symlink():
            raise HarnessError("lineage database cannot be a symlink")
        try:
            db = sqlite3.connect(self.path, timeout=10)
            db.execute("PRAGMA foreign_keys=ON")
        except sqlite3.Error as exc:
            raise HarnessError("cannot open lineage database") from exc
        try:
            with db:
                yield db
        finally:
            db.close()

    def register(self, digest: str) -> None:
        """Register a fully intact object-store manifest; idempotent."""
        self.store.get_manifest(digest)
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO nodes(id) VALUES (?)", (digest,))

    def initialize_baseline(self, digest: str) -> None:
        """Set the adopted metadata once, only to the current packaged manifest."""
        baseline = content_hash(canonical_manifest(default_manifest()))
        if digest != baseline:
            raise HarnessError("baseline must match the packaged harness")
        self.store.get_manifest(digest)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO nodes(id) VALUES (?)", (digest,))
            old = db.execute("SELECT node FROM refs WHERE name=?", (_ADOPTED,)).fetchone()
            if old:
                if old[0] != digest:
                    raise HarnessError("adopted ref cannot be changed")
                return
            db.execute("INSERT INTO refs(name,node) VALUES (?,?)", (_ADOPTED, digest))
            db.execute(
                "INSERT INTO ref_history(name,old_node,new_node) VALUES (?,NULL,?)",
                (_ADOPTED, digest),
            )

    def set_candidate(self, name: str, digest: str, *, expected: str | None = None) -> None:
        """Compare-and-set a candidate metadata ref; never update adopted."""
        if type(name) is not str or not _CANDIDATE.fullmatch(name):
            raise HarnessError("invalid candidate ref")
        self.store.get_manifest(digest)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM nodes WHERE id=?", (digest,)).fetchone():
                raise HarnessError("candidate manifest is not registered")
            row = db.execute("SELECT node FROM refs WHERE name=?", (name,)).fetchone()
            previous = row[0] if row else None
            if previous != expected:
                raise HarnessError("candidate ref changed; compare-and-set failed")
            if previous == digest:
                return
            db.execute(
                "INSERT INTO refs(name,node) VALUES (?,?) ON CONFLICT(name) DO UPDATE SET node=excluded.node",
                (name, digest),
            )
            db.execute(
                "INSERT INTO ref_history(name,old_node,new_node) VALUES (?,?,?)",
                (name, previous, digest),
            )

    def resolve(self, name: str) -> str:
        if name != _ADOPTED and (type(name) is not str or not _CANDIDATE.fullmatch(name)):
            raise HarnessError("invalid ref")
        with self._connect() as db:
            row = db.execute("SELECT node FROM refs WHERE name=?", (name,)).fetchone()
        if not row:
            raise HarnessError("unknown ref")
        self.store.get_manifest(row[0])
        return row[0]

    def add_edge(
        self,
        child: str,
        parent: str,
        *,
        task: str,
        trajectory_ids: tuple[str, ...] = (),
        judge_report: str = "",
        decision: str = "proposed",
    ) -> None:
        """Record an immutable edge; cycle checks and insert share a write lock."""
        for value in (child, parent):
            self.store.get_manifest(value)
        if child == parent:
            raise HarnessError("lineage cycle")
        if type(task) is not str or not task.strip() or len(task) > 1000:
            raise HarnessError("invalid task")
        if type(judge_report) is not str or len(judge_report) > 512:
            raise HarnessError("invalid judge report")
        if (
            type(trajectory_ids) is not tuple
            or len(trajectory_ids) > 64
            or any(type(x) is not str or not x or len(x) > 256 for x in trajectory_ids)
        ):
            raise HarnessError("invalid trajectory identifiers")
        if type(decision) is not str or decision not in _DECISIONS:
            raise HarnessError("invalid or unsupported lineage decision")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for value in (child, parent):
                if not db.execute("SELECT 1 FROM nodes WHERE id=?", (value,)).fetchone():
                    raise HarnessError("lineage manifest is not registered")
            cycle = db.execute(
                """
                WITH RECURSIVE ancestors(id) AS (
                    SELECT ? UNION SELECT edges.parent FROM edges JOIN ancestors ON edges.child=ancestors.id
                ) SELECT 1 FROM ancestors WHERE id=?
            """,
                (parent, child),
            ).fetchone()
            if cycle:
                raise HarnessError("lineage cycle")
            try:
                db.execute(
                    "INSERT INTO edges(child,parent,task,trajectories,judge_report,decision) VALUES (?,?,?,?,?,?)",
                    (
                        child,
                        parent,
                        task,
                        json.dumps(trajectory_ids, separators=(",", ":")),
                        judge_report,
                        decision,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise HarnessError("lineage edge already recorded") from exc

    def parents(self, child: str) -> tuple[LineageEdge, ...]:
        self.store.get_manifest(child)
        with self._connect() as db:
            if not db.execute("SELECT 1 FROM nodes WHERE id=?", (child,)).fetchone():
                raise HarnessError("lineage manifest is not registered")
            rows = db.execute(
                "SELECT child,parent,task,trajectories,judge_report,decision FROM edges WHERE child=? ORDER BY parent",
                (child,),
            ).fetchall()
        result = []
        for c, parent, task, trajectories, report, decision in rows:
            self.store.get_manifest(parent)
            result.append(
                LineageEdge(c, parent, task, tuple(json.loads(trajectories)), report, decision)
            )
        return tuple(result)

    def history(self, name: str) -> tuple[tuple[str | None, str], ...]:
        if name != _ADOPTED and (type(name) is not str or not _CANDIDATE.fullmatch(name)):
            raise HarnessError("invalid ref")
        with self._connect() as db:
            rows = db.execute(
                "SELECT old_node,new_node FROM ref_history WHERE name=? ORDER BY seq", (name,)
            ).fetchall()
        return tuple((old, new) for old, new in rows)
