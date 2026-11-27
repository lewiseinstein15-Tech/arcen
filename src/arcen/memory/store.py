"""ARCEN — memory store (BACKEND-SPEC Part 5).

Single SQLite file: ``~/.arcen/memory.db``, WAL mode. All state —
entities, relations, facts, usage counters — lives in that one file so
backup is ``cp``.

The five GraphMem innovations (pulled from the graph-memory work in
Letta + Graphiti, reduced to SQLite):

1. Decay        — facts carry a half-life (default 14 days). Unaccessed
                  facts lose weight; below threshold they are archived,
                  never deleted.
2. Consolidation— repeated observations merge into one stronger fact
                  with a source list.
3. Conflicts    — a fact that contradicts an active one (same entity,
                  same key, different text) supersedes it; the old fact
                  is kept as history with ``invalid_at``, never silently
                  overwritten.
4. Temporality  — every fact is queryable "as of" a time; recall
                  defaults to now.
5. Prioritization— recall ranks by weight × recency × graph centrality,
                  capped at k so prompts stay small.

DRAFT recalls before planning; TEMPER records verified outcomes; every
turn writes what it learned (the ``memory`` event on the stream).
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import time

from .graph import MemoryGraph

DEFAULT_HALF_LIFE_DAYS = 14.0
ARCHIVE_THRESHOLD = 0.1

# Tokens too common to signal relatedness between two goals.
_STOPWORDS = frozenset(
    ["a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have", "in", "into", "is", "it", "its", "of", "on", "or", "that", "the", "then", "this", "to", "with", "all", "any", "can", "create", "do", "does", "file", "files", "make", "new", "not", "use", "using", "write"]
)
_WORD = re.compile(r"[a-z0-9_]{3,}")
# A goal naming the same path as an earlier one is evidence, not coincidence,
# even when the path is the only shared token ("fizzbuzz.py" alone).
_PATH = re.compile(
    r"[a-z0-9_./-]+\.(?:py|pyi|ts|tsx|js|jsx|go|rs|java|rb|sh|json|ya?ml|toml|md|sql|css|html)"
)


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOPWORDS}


def _paths(text: str) -> set[str]:
    return {p.rstrip("./") for p in _PATH.findall(text.lower())}


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


class MemoryStore:
    """Facts + entity graph in one SQLite file."""

    def __init__(self, path: str = "~/.arcen/memory.db", half_life_days: float = DEFAULT_HALF_LIFE_DAYS) -> None:
        import os

        expanded = os.path.expanduser(path)
        os.makedirs(os.path.dirname(expanded) or ".", exist_ok=True)
        self.path = expanded
        self.half_life_days = half_life_days
        self.conn = _connect(expanded)
        self.graph = MemoryGraph(self.conn)
        self._migrate()

    def _migrate(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity TEXT NOT NULL,
                key TEXT,
                fact TEXT NOT NULL,
                weight REAL NOT NULL DEFAULT 1.0,
                sources TEXT NOT NULL DEFAULT '[]',
                created_at REAL NOT NULL,
                last_accessed REAL NOT NULL,
                valid_from REAL NOT NULL,
                invalid_at REAL,
                archived INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_facts_entity ON facts(entity);
            CREATE INDEX IF NOT EXISTS idx_facts_key ON facts(entity, key);
            """
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # -- write ---------------------------------------------------------------
    def write(self, entity: str, fact: str, key: str | None = None, source: str = "turn", ts: float | None = None) -> dict:
        """Record one observation. Consolidates repeats, resolves conflicts.

        Returns {"op": "consolidated" | "superseded" | "new", "fact_id": id}.
        """
        now = ts if ts is not None else time.time()
        self.graph.touch_entity(entity)

        # 2 · consolidation: exact same (entity, key, fact) → stronger fact
        if key is None:
            key = fact.split(":")[0].strip().lower()[:64]
        row = self.conn.execute(
            """SELECT id, weight, sources, created_at FROM facts
               WHERE entity=? AND key=? AND fact=? AND archived=0 AND invalid_at IS NULL""",
            (entity, key, fact),
        ).fetchone()
        if row is not None:
            sources = json.loads(row["sources"])
            if source not in sources:
                sources.append(source)
            new_weight = row["weight"] + 1.0
            self.conn.execute(
                """UPDATE facts SET weight=?, sources=?, last_accessed=? WHERE id=?""",
                (new_weight, json.dumps(sources), now, row["id"]),
            )
            self.conn.commit()
            return {"op": "consolidated", "fact_id": row["id"], "weight": new_weight, "sources": sources}

        # 3 · conflict resolution: same key, different text → supersede
        conflict = self.conn.execute(
            """SELECT id, fact FROM facts
               WHERE entity=? AND key=? AND archived=0 AND invalid_at IS NULL""",
            (entity, key),
        ).fetchone()
        op = "new"
        if conflict is not None and conflict["fact"] != fact:
            self.conn.execute(
                "UPDATE facts SET invalid_at=? WHERE id=?",
                (now, conflict["id"]),
            )
            op = "superseded"

        cur = self.conn.execute(
            """INSERT INTO facts(entity, key, fact, weight, sources, created_at, last_accessed, valid_from)
               VALUES(?, ?, ?, 1.0, ?, ?, ?, ?)""",
            (entity, key, fact, json.dumps([source]), now, now, now),
        )
        self.conn.commit()
        return {"op": op, "fact_id": cur.lastrowid, "superseded": conflict["id"] if conflict is not None and op == "superseded" else None}

    # -- recall ----------------------------------------------------------------
    def recall(self, entity: str, k: int = 5, as_of: float | None = None, touch: bool = True) -> list[dict]:
        """Rank by weight × recency × centrality; top k. Temporal by default."""
        moment = as_of if as_of is not None else time.time()
        centrality = self.graph.centrality(entity)
        rows = self.conn.execute(
            """SELECT id, entity, key, fact, weight, sources, created_at, last_accessed, valid_from, invalid_at
               FROM facts
               WHERE entity=? AND archived=0 AND valid_from<=?
                 AND (invalid_at IS NULL OR invalid_at>?)""",
            (entity, moment, moment),
        ).fetchall()
        scored = []
        for r in rows:
            days_stale = max(0.0, (moment - r["last_accessed"]) / 86400.0)
            recency = math.pow(0.5, days_stale / self.half_life_days)
            score = r["weight"] * recency * (1.0 + centrality)
            scored.append(
                {
                    "id": r["id"],
                    "entity": r["entity"],
                    "fact": r["fact"],
                    "key": r["key"],
                    "weight": r["weight"],
                    "sources": json.loads(r["sources"]),
                    "score": round(score, 6),
                    "created_at": r["created_at"],
                    "invalid_at": r["invalid_at"],
                }
            )
        scored.sort(key=lambda f: f["score"], reverse=True)
        if touch and as_of is None and scored:
            ids = [f["id"] for f in scored[:k]]
            self.conn.executemany(
                "UPDATE facts SET last_accessed=? WHERE id=?",
                [(time.time(), i) for i in ids],
            )
            self.conn.commit()
        return scored[:k]

    def history(self, entity: str, key: str) -> list[dict]:
        """Every version of a key's fact, including superseded ones."""
        rows = self.conn.execute(
            """SELECT id, fact, weight, valid_from, invalid_at, archived
               FROM facts WHERE entity=? AND key=? ORDER BY valid_from""",
            (entity, key),
        ).fetchall()
        return [dict(r) for r in rows]

    def recall_related(self, text: str, k: int = 5, min_overlap: int = 2) -> list[dict]:
        """Facts whose entity or text shares meaningful terms with ``text``.

        ``recall`` needs an exact entity, which is why memory was write-only
        in the turn path: a new goal rarely matches a previous goal string.
        This ranks live facts by token overlap so a later turn can reuse
        earlier conclusions. Scoring is lexical and explainable — no
        embeddings, no hidden state — and ties break by weight then recency.

        ``min_overlap`` filters out single-token coincidences ("test", "the").
        A shared file path overrides that floor: two goals naming ``calc.py``
        are related even when it is the only token they have in common.
        """
        tokens = _tokens(text)
        paths = _paths(text)
        if not tokens:
            return []
        rows = self.conn.execute(
            """SELECT id, entity, key, fact, weight, last_accessed, created_at
               FROM facts WHERE archived=0 AND invalid_at IS NULL"""
        ).fetchall()
        now = time.time()
        scored: list[dict] = []
        for r in rows:
            candidate = f"{r['entity']} {r['fact']}"
            overlap = tokens & _tokens(candidate)
            shared_paths = paths & _paths(candidate)
            if len(overlap) < min_overlap and not shared_paths:
                continue
            days_stale = max(0.0, (now - r["last_accessed"]) / 86400.0)
            recency = math.pow(0.5, days_stale / self.half_life_days)
            score = (len(overlap) + 2 * len(shared_paths)) * r["weight"] * recency
            scored.append(
                {
                    "id": r["id"],
                    "entity": r["entity"],
                    "fact": r["fact"],
                    "key": r["key"],
                    "weight": r["weight"],
                    "score": round(score, 6),
                    "overlap": sorted(overlap | shared_paths),
                }
            )
        scored.sort(key=lambda f: (f["score"], f["weight"]), reverse=True)
        return scored[:k]

    # -- decay -----------------------------------------------------------------
    def decay(self, now: float | None = None) -> dict:
        """Apply the half-life; archive facts below the threshold.

        Archived — not deleted: history stays queryable.
        """
        moment = now if now is not None else time.time()
        rows = self.conn.execute(
            "SELECT id, weight, last_accessed FROM facts WHERE archived=0"
        ).fetchall()
        archived = 0
        for r in rows:
            days_stale = max(0.0, (moment - r["last_accessed"]) / 86400.0)
            effective = r["weight"] * math.pow(0.5, days_stale / self.half_life_days)
            if effective < ARCHIVE_THRESHOLD:
                self.conn.execute("UPDATE facts SET archived=1 WHERE id=?", (r["id"],))
                archived += 1
        self.conn.commit()
        return {"checked": len(rows), "archived": archived}

    def forget(self, fact_id: int) -> dict:
        """Explicit forget: archive the fact, keep the history."""
        cur = self.conn.execute("UPDATE facts SET archived=1 WHERE id=?", (fact_id,))
        self.conn.commit()
        return {"forgotten": cur.rowcount > 0, "fact_id": fact_id}

    def stats(self) -> dict:
        row = self.conn.execute(
            """SELECT
                 (SELECT COUNT(*) FROM entities) AS entities,
                 (SELECT COUNT(*) FROM relations) AS relations,
                 (SELECT COUNT(*) FROM facts WHERE archived=0) AS active_facts,
                 (SELECT COUNT(*) FROM facts WHERE archived=1) AS archived_facts"""
        ).fetchone()
        return dict(row)


def main(argv: list[str]) -> int:  # pragma: no cover — demo
    """`python -m arcen.memory.store` — store a fact, recall it."""
    import tempfile

    db = tempfile.mktemp(suffix=".db")
    store = MemoryStore(db)
    store.graph.relate("calc()", "tests/test_pay.py", "tested-by")
    print(store.write("calc()", "port is 3002", key="port", source="demo"))
    print(store.write("calc()", "port is 3003", key="port", source="demo"))
    print(store.write("calc()", "returns int sum", source="demo"))
    for fact in store.recall("calc()"):
        print(f"recall: [{fact['score']:.3f}] {fact['fact']} (sources: {fact['sources']})")
    print("stats:", store.stats())
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv))
