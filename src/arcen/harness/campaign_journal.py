"""Durable, fail-closed bookkeeping for manually initiated campaigns.

This is not an execution authority or authenticated log. Incomplete runs cannot
be resumed automatically: an interrupted external side effect is ambiguous.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import stat
import time
from contextlib import contextmanager
from dataclasses import dataclass

from .policy import review_candidate
from .resolver import HarnessError
from .store import HarnessStore

_ID = re.compile(r"[0-9a-f]{32}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class CampaignStopped(HarnessError):
    """A durable stop request prevented another campaign stage."""


@dataclass(frozen=True, slots=True)
class CampaignRecord:
    id: str
    baseline: str
    candidates: tuple[str, ...]
    task_sha256: str
    commit: str
    state: str
    phase: str
    cursor: int
    stop_requested: bool
    created_at: int
    updated_at: int
    reviews: tuple[str, ...]


class CampaignJournal:
    """Metadata-only campaign journal; never stores a task or trajectory."""

    def __init__(self, store: HarnessStore, *, create: bool = False):
        if type(store) is not HarnessStore or type(create) is not bool:
            raise HarnessError("invalid campaign journal settings")
        self.store = store
        self.path = store.root / "campaigns.sqlite3"
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
                    raise HarnessError("campaign database must be a regular file")
            except OSError:
                raise HarnessError("cannot create campaign database") from None
            else:
                os.close(fd)
        elif self.path.is_symlink() or not self.path.is_file():
            raise HarnessError("campaign database is missing or invalid")
        with self._connect(read_only=not create) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in ((0, 1) if create else (1,)):
                raise HarnessError("unsupported campaign database schema")
            if version == 0:
                if (
                    not create
                    or db.execute(
                        "SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1"
                    ).fetchone()
                ):
                    raise HarnessError("invalid campaign database schema")
                db.executescript("""
                    CREATE TABLE campaigns (
                        id TEXT PRIMARY KEY NOT NULL, baseline TEXT NOT NULL,
                        candidates TEXT NOT NULL, task_sha256 TEXT NOT NULL,
                        commit_id TEXT NOT NULL, state TEXT NOT NULL, phase TEXT NOT NULL,
                        cursor INTEGER NOT NULL, stop_requested INTEGER NOT NULL,
                        created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
                    );
                    CREATE TABLE campaign_reviews (
                        campaign_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
                        candidate TEXT NOT NULL, review_id TEXT NOT NULL,
                        PRIMARY KEY(campaign_id, ordinal), UNIQUE(campaign_id, review_id)
                    );
                    PRAGMA user_version=1;
                """)
            self._validate_schema(db)

    @staticmethod
    def _validate_schema(db: sqlite3.Connection) -> None:
        objects = set(
            db.execute(
                "SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            ).fetchall()
        )
        expected = {
            "campaigns": [
                ("id", "TEXT", 1),
                ("baseline", "TEXT", 0),
                ("candidates", "TEXT", 0),
                ("task_sha256", "TEXT", 0),
                ("commit_id", "TEXT", 0),
                ("state", "TEXT", 0),
                ("phase", "TEXT", 0),
                ("cursor", "INTEGER", 0),
                ("stop_requested", "INTEGER", 0),
                ("created_at", "INTEGER", 0),
                ("updated_at", "INTEGER", 0),
            ],
            "campaign_reviews": [
                ("campaign_id", "TEXT", 1),
                ("ordinal", "INTEGER", 2),
                ("candidate", "TEXT", 0),
                ("review_id", "TEXT", 0),
            ],
        }
        columns = {}
        indexes = {}
        for name in expected:
            rows = db.execute(f"PRAGMA table_info({name})").fetchall()
            columns[name] = [(r[1], r[2], r[5]) for r in rows]
            if any(r[3] != 1 or r[4] is not None for r in rows):
                raise HarnessError("invalid campaign database schema")
            indexes[name] = {
                (r[3], tuple(x[2] for x in db.execute(f"PRAGMA index_info('{r[1]}')")))
                for r in db.execute(f"PRAGMA index_list({name})")
                if r[2] == 1 and r[4] == 0
            }
        if (
            objects != {("table", "campaigns"), ("table", "campaign_reviews")}
            or columns != expected
            or indexes
            != {
                "campaigns": {("pk", ("id",))},
                "campaign_reviews": {
                    ("pk", ("campaign_id", "ordinal")),
                    ("u", ("campaign_id", "review_id")),
                },
            }
        ):
            raise HarnessError("invalid campaign database schema")

    @contextmanager
    def _connect(self, *, read_only: bool = False):
        self.store._path("0" * 64)
        if self.path.is_symlink() or not self.path.is_file():
            raise HarnessError("campaign database is missing or invalid")
        try:
            uri = self.path.absolute().as_uri() + ("?mode=ro" if read_only else "?mode=rw")
            db = sqlite3.connect(uri, timeout=10, uri=True)
        except sqlite3.Error:
            raise HarnessError("cannot open campaign database") from None
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _inputs(
        baseline: str, candidates: tuple[str, ...], task: str, commit: str
    ) -> tuple[str, str]:
        if (
            type(baseline) is not str
            or not _HASH.fullmatch(baseline)
            or type(candidates) is not tuple
            or not 1 <= len(candidates) <= 5
            or any(type(x) is not str or not _HASH.fullmatch(x) for x in candidates)
            or len(set(candidates)) != len(candidates)
            or baseline in candidates
            or type(commit) is not str
            or not _COMMIT.fullmatch(commit)
            or type(task) is not str
            or not task.strip()
            or len(task) > 4000
        ):
            raise HarnessError("invalid campaign plan")
        try:
            digest = hashlib.sha256(task.encode("utf-8")).hexdigest()
        except UnicodeError:
            raise HarnessError("invalid campaign task") from None
        return json.dumps(candidates, separators=(",", ":")), digest

    def plan(
        self, baseline: str, candidates: tuple[str, ...], task: str, commit: str
    ) -> CampaignRecord:
        encoded, digest = self._inputs(baseline, candidates, task, commit)
        for candidate in candidates:
            review_candidate(self.store, baseline, candidate)
        identifier = secrets.token_hex(16)
        now = int(time.time())
        if now < 0:
            raise HarnessError("invalid campaign clock")
        with self._connect() as db:
            db.execute(
                "INSERT INTO campaigns VALUES (?,?,?,?,?,'ready','ready',0,0,?,?)",
                (identifier, baseline, encoded, digest, commit, now, now),
            )
        return self.get(identifier)

    def get(self, identifier: str) -> CampaignRecord:
        if type(identifier) is not str or not _ID.fullmatch(identifier):
            raise HarnessError("invalid campaign identifier")
        with self._connect(read_only=True) as db:
            db.execute("BEGIN")
            row = db.execute(
                "SELECT id,baseline,candidates,task_sha256,commit_id,state,phase,cursor,stop_requested,created_at,updated_at FROM campaigns WHERE id=?",
                (identifier,),
            ).fetchone()
            reviews = db.execute(
                "SELECT ordinal,candidate,review_id FROM campaign_reviews WHERE campaign_id=? ORDER BY ordinal",
                (identifier,),
            ).fetchall()
        if row is None:
            raise HarnessError("unknown campaign")
        try:
            parsed = json.loads(row[2])
            candidates = tuple(parsed) if type(parsed) is list else ()
        except (TypeError, ValueError):
            raise HarnessError("invalid campaign record") from None
        if (
            not 1 <= len(candidates) <= 5
            or any(type(x) is not str or not _HASH.fullmatch(x) for x in candidates)
            or len(set(candidates)) != len(candidates)
            or type(row[1]) is not str
            or not _HASH.fullmatch(row[1])
            or row[1] in candidates
            or type(row[3]) is not str
            or not _HASH.fullmatch(row[3])
            or type(row[4]) is not str
            or not _COMMIT.fullmatch(row[4])
            or row[5] not in {"ready", "running", "stopped", "failed", "completed"}
            or row[6] not in {"ready", "reference", "candidate", "judge", "recording", "done"}
            or type(row[7]) is not int
            or not 0 <= row[7] <= len(candidates)
            or row[8] not in (0, 1)
            or type(row[9]) is not int
            or type(row[10]) is not int
            or row[9] < 0
            or row[10] < row[9]
            or len(reviews) != row[7]
            or any(
                n != i
                or candidate != candidates[i]
                or type(review) is not str
                or not _ID.fullmatch(review)
                for i, (n, candidate, review) in enumerate(reviews)
            )
            or (row[5] == "ready" and (row[6] != "ready" or row[7] != 0 or row[8] != 0))
            or (row[5] == "completed" and (row[6] != "done" or row[7] != len(candidates)))
            or (row[5] == "running" and (row[6] in {"ready", "done"} or row[7] >= len(candidates)))
        ):
            raise HarnessError("invalid campaign record")
        return CampaignRecord(
            row[0],
            row[1],
            candidates,
            row[3],
            row[4],
            row[5],
            row[6],
            row[7],
            bool(row[8]),
            row[9],
            row[10],
            tuple(x[2] for x in reviews),
        )

    def claim(
        self, identifier: str, baseline: str, candidates: tuple[str, ...], task: str, commit: str
    ) -> None:
        encoded, digest = self._inputs(baseline, candidates, task, commit)
        record = self.get(identifier)
        if (
            record.state != "ready"
            or record.baseline != baseline
            or record.candidates != candidates
            or record.task_sha256 != digest
            or record.commit != commit
        ):
            raise HarnessError("campaign plan mismatch or already started")
        with self._connect() as db:
            changed = db.execute(
                "UPDATE campaigns SET state='running',phase='reference',updated_at=MAX(updated_at,?) WHERE id=? AND state='ready' AND baseline=? AND candidates=? AND task_sha256=? AND commit_id=? AND stop_requested=0",
                (int(time.time()), identifier, baseline, encoded, digest, commit),
            ).rowcount
            if changed != 1:
                raise HarnessError("campaign plan mismatch or already started")

    def request_stop(self, identifier: str) -> CampaignRecord:
        self.get(identifier)
        with self._connect() as db:
            db.execute(
                "UPDATE campaigns SET stop_requested=1,state=CASE WHEN state='ready' THEN 'stopped' ELSE state END,updated_at=MAX(updated_at,?) WHERE id=? AND state IN ('ready','running')",
                (int(time.time()), identifier),
            )
        return self.get(identifier)

    def checkpoint(self, identifier: str, phase: str, cursor: int) -> None:
        record = self.get(identifier)
        if record.state != "running" or record.phase != phase or record.cursor != cursor:
            raise HarnessError("campaign checkpoint refused")
        stopped = False
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT state,phase,cursor,stop_requested FROM campaigns WHERE id=?", (identifier,)
            ).fetchone()
            if row is None or row[:3] != ("running", phase, cursor):
                raise HarnessError("campaign checkpoint refused")
            stopped = bool(row[3])
            if stopped:
                db.execute(
                    "UPDATE campaigns SET state='stopped',updated_at=MAX(updated_at,?) WHERE id=?",
                    (int(time.time()), identifier),
                )
        if stopped:
            raise CampaignStopped("campaign stop requested")

    def advance(self, identifier: str, expected: str, next_phase: str) -> None:
        transitions = {"reference": "candidate", "candidate": "judge", "judge": "recording"}
        if transitions.get(expected) != next_phase:
            raise HarnessError("invalid campaign transition")
        self.get(identifier)
        stopped = False
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT state,phase,stop_requested FROM campaigns WHERE id=?", (identifier,)
            ).fetchone()
            if row is None or row[0] != "running" or row[1] != expected:
                raise HarnessError("campaign transition refused")
            stopped = bool(row[2])
            db.execute(
                "UPDATE campaigns SET state=?,phase=?,updated_at=MAX(updated_at,?) WHERE id=?",
                (
                    "stopped" if stopped else "running",
                    expected if stopped else next_phase,
                    int(time.time()),
                    identifier,
                ),
            )
        if stopped:
            raise CampaignStopped("campaign stop requested")

    def record_review(self, identifier: str, candidate: str, review_id: str) -> CampaignRecord:
        if type(review_id) is not str or not _ID.fullmatch(review_id):
            raise HarnessError("invalid campaign review identifier")
        record = self.get(identifier)
        if (
            record.state != "running"
            or record.phase != "recording"
            or record.cursor >= len(record.candidates)
            or candidate != record.candidates[record.cursor]
        ):
            raise HarnessError("campaign review transition refused")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT state,phase,cursor,stop_requested FROM campaigns WHERE id=?", (identifier,)
            ).fetchone()
            if (
                row is None
                or row[0] != "running"
                or row[1] != "recording"
                or row[2] != record.cursor
            ):
                raise HarnessError("campaign review transition refused")
            db.execute(
                "INSERT INTO campaign_reviews VALUES (?,?,?,?)",
                (identifier, record.cursor, candidate, review_id),
            )
            cursor = record.cursor + 1
            state = (
                "stopped"
                if row[3]
                else "completed"
                if cursor == len(record.candidates)
                else "running"
            )
            phase = (
                "done"
                if state == "completed"
                else "recording"
                if state == "stopped"
                else "candidate"
            )
            db.execute(
                "UPDATE campaigns SET cursor=?,state=?,phase=?,updated_at=MAX(updated_at,?) WHERE id=?",
                (cursor, state, phase, int(time.time()), identifier),
            )
        return self.get(identifier)

    def fail(self, identifier: str) -> None:
        self.get(identifier)
        with self._connect() as db:
            changed = db.execute(
                "UPDATE campaigns SET state=CASE WHEN stop_requested=1 THEN 'stopped' ELSE 'failed' END,updated_at=MAX(updated_at,?) WHERE id=? AND state='running'",
                (int(time.time()), identifier),
            ).rowcount
            if changed != 1:
                raise HarnessError("campaign finalization refused")
