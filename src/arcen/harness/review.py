"""Durable local review decisions. No decision can adopt a harness.

The store and local caller are trusted; records are neither signed nor proof of
human identity. A later adoption gate must independently recheck all evidence.
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

from .comparison import ReviewedComparison
from .judge import Judgment
from .policy import review_candidate
from .probe_execution import ReviewedProbeResult
from .resolver import HarnessError
from .store import HarnessStore

_ID = re.compile(r"[0-9a-f]{32}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


@dataclass(frozen=True, slots=True)
class ReviewRecord:
    id: str
    baseline_id: str
    candidate_id: str
    source: str
    commit: str | None
    workspace_sha256: str | None
    judge_winner: str | None
    judge_confidence: float | None
    state: str
    created_at: int
    reviewer: str | None
    note: str | None
    decided_at: int | None


class ReviewLedger:
    """Compare-and-set human review metadata, not a ref or adoption authority."""

    def __init__(self, store: HarnessStore, *, create: bool = False):
        self.store = store
        self.path = store.root / "reviews.sqlite3"
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
                    raise HarnessError("review database must be a regular file")
            except OSError:
                raise HarnessError("cannot create review database") from None
            else:
                os.close(fd)
        elif self.path.is_symlink() or not self.path.is_file():
            raise HarnessError("review database is missing or invalid")
        with self._connect(read_only=not create) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in ((0, 1) if create else (1,)):
                raise HarnessError("unsupported review database schema")
            if version == 0:
                if (
                    not create
                    or db.execute(
                        "SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1"
                    ).fetchone()
                ):
                    raise HarnessError("invalid review database schema")
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS reviews (
                        id TEXT PRIMARY KEY NOT NULL,
                        baseline TEXT NOT NULL,
                        candidate TEXT NOT NULL,
                        source TEXT NOT NULL CHECK(source IN ('static', 'paired')),
                        commit_id TEXT,
                        workspace TEXT,
                        winner TEXT,
                        confidence REAL,
                        state TEXT NOT NULL CHECK(state IN ('pending', 'approved', 'rejected')),
                        created_at INTEGER NOT NULL,
                        reviewer TEXT,
                        note TEXT,
                        decided_at INTEGER
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS one_pending_review
                        ON reviews(baseline, candidate, source) WHERE state = 'pending';
                    PRAGMA user_version = 1;
                """)
            self._validate_schema(db)

    @staticmethod
    def _validate_schema(db: sqlite3.Connection) -> None:
        expected = [
            ("id", "TEXT", 1, 1),
            ("baseline", "TEXT", 1, 0),
            ("candidate", "TEXT", 1, 0),
            ("source", "TEXT", 1, 0),
            ("commit_id", "TEXT", 0, 0),
            ("workspace", "TEXT", 0, 0),
            ("winner", "TEXT", 0, 0),
            ("confidence", "REAL", 0, 0),
            ("state", "TEXT", 1, 0),
            ("created_at", "INTEGER", 1, 0),
            ("reviewer", "TEXT", 0, 0),
            ("note", "TEXT", 0, 0),
            ("decided_at", "INTEGER", 0, 0),
        ]
        columns = [(r[1], r[2], r[3], r[5]) for r in db.execute("PRAGMA table_info(reviews)")]
        objects = set(
            db.execute(
                "SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            ).fetchall()
        )
        idx = db.execute("SELECT sql FROM sqlite_master WHERE name='one_pending_review'").fetchone()
        index_sql = " ".join(idx[0].lower().split()) if idx and type(idx[0]) is str else ""
        if (
            columns != expected
            or objects != {("table", "reviews"), ("index", "one_pending_review")}
            or index_sql
            != "create unique index one_pending_review on reviews(baseline, candidate, source) where state = 'pending'"
        ):
            raise HarnessError("invalid review database schema")

    @contextmanager
    def _connect(self, *, read_only: bool = False):
        self.store._path("0" * 64)
        if self.path.is_symlink() or not self.path.is_file():
            raise HarnessError("review database is missing or invalid")
        try:
            uri = self.path.absolute().as_uri() + ("?mode=ro" if read_only else "?mode=rw")
            db = sqlite3.connect(uri, timeout=10, uri=True)
        except sqlite3.Error:
            raise HarnessError("cannot open review database") from None
        try:
            with db:
                yield db
        finally:
            db.close()

    def request(self, baseline_id: str, candidate_id: str) -> ReviewRecord:
        """Create a static pending request; it cannot be approved as tested."""
        review_candidate(self.store, baseline_id, candidate_id)
        return self._insert(baseline_id, candidate_id, "static", None, None, None, None)

    def request_from_comparison(self, pair: ReviewedComparison) -> ReviewRecord:
        """Record supplied successful paired evidence; this does not authenticate it."""
        if type(pair) is not ReviewedComparison or pair.candidate is None or pair.judgment is None:
            raise HarnessError("completed paired comparison is required")
        ref, cand, verdict = pair.reference, pair.candidate, pair.judgment
        if (
            type(ref) is not ReviewedProbeResult
            or type(cand) is not ReviewedProbeResult
            or type(verdict) is not Judgment
        ):
            raise HarnessError("invalid paired comparison evidence")
        baseline_id, candidate_id = ref.baseline_id, cand.candidate_id
        if (
            ref.status != "ok"
            or cand.status != "ok"
            or any(
                type(result.events) is not tuple
                or not result.events
                or type(result.events[-1]) is not dict
                or result.events[-1].get("type") != "run.done"
                or result.events[-1].get("status") != "ok"
                for result in (ref, cand)
            )
            or ref.candidate_id != baseline_id
            or cand.baseline_id != baseline_id
            or baseline_id == candidate_id
            or type(ref.commit) is not str
            or not _COMMIT.fullmatch(ref.commit)
            or ref.commit != cand.commit
            or type(ref.workspace_sha256) is not str
            or not _HASH.fullmatch(ref.workspace_sha256)
            or ref.workspace_sha256 != cand.workspace_sha256
            or type(verdict.winner) is not str
            or verdict.winner not in {"reference", "candidate", "tie"}
            or type(verdict.confidence) not in (int, float)
            or not math.isfinite(verdict.confidence)
            or not 0 <= verdict.confidence <= 1
        ):
            raise HarnessError("inconsistent paired comparison evidence")
        review_candidate(self.store, baseline_id, candidate_id)
        return self._insert(
            baseline_id,
            candidate_id,
            "paired",
            ref.commit,
            ref.workspace_sha256,
            verdict.winner,
            float(verdict.confidence),
        )

    def _insert(
        self,
        baseline: str,
        candidate: str,
        source: str,
        commit: str | None,
        workspace: str | None,
        winner: str | None,
        confidence: float | None,
    ) -> ReviewRecord:
        identifier = secrets.token_hex(16)
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        identifier,
                        baseline,
                        candidate,
                        source,
                        commit,
                        workspace,
                        winner,
                        confidence,
                        "pending",
                        int(time.time()),
                        None,
                        None,
                        None,
                    ),
                )
        except sqlite3.IntegrityError:
            raise HarnessError("a pending review for these manifests already exists") from None
        return self.get(identifier)

    def get(self, identifier: str) -> ReviewRecord:
        if type(identifier) is not str or not _ID.fullmatch(identifier):
            raise HarnessError("invalid review identifier")
        with self._connect(read_only=True) as db:
            row = db.execute(
                "SELECT id,baseline,candidate,source,commit_id,workspace,winner,confidence,state,created_at,reviewer,note,decided_at FROM reviews WHERE id=?",
                (identifier,),
            ).fetchone()
        if row is None:
            raise HarnessError("unknown review")
        record = ReviewRecord(*row)
        self._check_record(record)
        return record

    def list(self, limit: int = 50) -> tuple[ReviewRecord, ...]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise HarnessError("invalid review list limit")
        with self._connect(read_only=True) as db:
            rows = db.execute(
                "SELECT id FROM reviews ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
        return tuple(self.get(row[0]) for row in rows)

    def resolve(
        self,
        identifier: str,
        decision: str,
        reviewer: str,
        note: str = "",
        *,
        saw_diff: bool = False,
        expected: ReviewRecord | None = None,
    ) -> ReviewRecord:
        """Record one explicit decision. It never changes or selects any ref."""
        if decision not in ("approved", "rejected"):
            raise HarnessError("invalid review decision")
        if type(reviewer) is not str or not reviewer.strip() or len(reviewer) > 80:
            raise HarnessError("invalid reviewer label")
        if type(note) is not str or len(note) > 512:
            raise HarnessError("invalid review note")
        if saw_diff is not True:
            raise HarnessError("explicit diff review is required")
        current = self.get(identifier)
        if expected is not None and (type(expected) is not ReviewRecord or current != expected):
            raise HarnessError("review changed since it was displayed")
        if current.state != "pending":
            raise HarnessError("review already decided")
        if decision == "approved" and current.source != "paired":
            raise HarnessError("approval requires successful paired comparison evidence")
        review_candidate(self.store, current.baseline_id, current.candidate_id)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                """UPDATE reviews SET state=?,reviewer=?,note=?,decided_at=?
                WHERE id=? AND state='pending' AND baseline=? AND candidate=? AND source=?
                AND commit_id IS ? AND workspace IS ? AND winner IS ? AND confidence IS ?
                AND created_at=?""",
                (
                    decision,
                    reviewer.strip(),
                    note,
                    max(int(time.time()), current.created_at),
                    identifier,
                    current.baseline_id,
                    current.candidate_id,
                    current.source,
                    current.commit,
                    current.workspace_sha256,
                    current.judge_winner,
                    current.judge_confidence,
                    current.created_at,
                ),
            ).rowcount
            if changed != 1:
                raise HarnessError("review already decided")
        return self.get(identifier)

    def _check_record(self, record: ReviewRecord) -> None:
        if (
            type(record.id) is not str
            or not _ID.fullmatch(record.id)
            or record.state not in {"pending", "approved", "rejected"}
            or record.source not in {"static", "paired"}
            or type(record.created_at) is not int
            or record.created_at < 0
            or (
                record.state == "pending"
                and any(x is not None for x in (record.reviewer, record.note, record.decided_at))
            )
            or (
                record.state != "pending"
                and (
                    type(record.reviewer) is not str
                    or not record.reviewer.strip()
                    or len(record.reviewer) > 80
                    or type(record.note) is not str
                    or len(record.note) > 512
                    or type(record.decided_at) is not int
                    or record.decided_at < record.created_at
                )
            )
        ):
            raise HarnessError("invalid review record")
        if record.source == "static":
            if (
                any(
                    x is not None
                    for x in (
                        record.commit,
                        record.workspace_sha256,
                        record.judge_winner,
                        record.judge_confidence,
                    )
                )
                or record.state == "approved"
            ):
                raise HarnessError("invalid static review record")
        elif (
            type(record.commit) is not str
            or not _COMMIT.fullmatch(record.commit)
            or type(record.workspace_sha256) is not str
            or not _HASH.fullmatch(record.workspace_sha256)
            or record.judge_winner not in {"reference", "candidate", "tie"}
            or type(record.judge_confidence) not in (int, float)
            or not math.isfinite(record.judge_confidence)
            or not 0 <= record.judge_confidence <= 1
        ):
            raise HarnessError("invalid paired review record")
        review_candidate(self.store, record.baseline_id, record.candidate_id)
