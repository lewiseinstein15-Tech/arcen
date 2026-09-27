"""ARCEN — memory graph (BACKEND-SPEC Part 5, pulled from Letta + Graphiti).

Memory is a graph, not a log: entities are nodes (``calc()``,
``tests/test_pay.py``, ``anthropic``), relations are typed edges.
Reduced to a single SQLite file so backup is ``cp``.

Graph duties:
- node/edge CRUD with timestamps;
- degree centrality — the cheap centrality that recall prioritization
  needs (a fact on a well-connected entity matters more);
- neighbors for traversal (DRAFT recalls before planning).
"""

from __future__ import annotations

import sqlite3
import time


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


class MemoryGraph:
    """The entity graph inside the shared SQLite file."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._migrate()

    def _migrate(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS entities (
                name TEXT PRIMARY KEY,
                kind TEXT NOT NULL DEFAULT 'thing',
                first_seen REAL NOT NULL,
                last_seen REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                src TEXT NOT NULL REFERENCES entities(name),
                dst TEXT NOT NULL REFERENCES entities(name),
                kind TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_relations_src ON relations(src);
            CREATE INDEX IF NOT EXISTS idx_relations_dst ON relations(dst);
            """
        )
        self.conn.commit()

    # -- entities --------------------------------------------------------------
    def touch_entity(self, name: str, kind: str = "thing") -> None:
        now = time.time()
        self.conn.execute(
            """INSERT INTO entities(name, kind, first_seen, last_seen)
               VALUES(?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET last_seen=excluded.last_seen""",
            (name, kind, now, now),
        )
        self.conn.commit()

    def entity_exists(self, name: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM entities WHERE name=?", (name,)).fetchone()
        return row is not None

    def neighbors(self, entity: str) -> list[dict]:
        rows = self.conn.execute(
            """SELECT src, dst, kind FROM relations
               WHERE src=? OR dst=? ORDER BY created_at""",
            (entity, entity),
        ).fetchall()
        return [
            {"neighbor": (r["dst"] if r["src"] == entity else r["src"]), "kind": r["kind"]}
            for r in rows
        ]

    def relate(self, src: str, dst: str, kind: str) -> None:
        self.touch_entity(src)
        self.touch_entity(dst)
        self.conn.execute(
            "INSERT INTO relations(src, dst, kind, created_at) VALUES(?, ?, ?, ?)",
            (src, dst, kind, time.time()),
        )
        self.conn.commit()

    # -- centrality ---------------------------------------------------------------
    def centrality(self, entity: str) -> float:
        """Degree centrality, normalized by the max degree in the graph."""
        row = self.conn.execute(
            """SELECT COUNT(*) AS deg FROM relations WHERE src=? OR dst=?""",
            (entity, entity),
        ).fetchone()
        degree = row["deg"]
        if degree == 0:
            return 0.0
        max_row = self.conn.execute(
            """SELECT MAX(deg) AS m FROM (
                 SELECT COUNT(*) AS deg FROM relations GROUP BY src
                 UNION ALL
                 SELECT COUNT(*) AS deg FROM relations GROUP BY dst
               )"""
        ).fetchone()
        top = max_row["m"] or 1
        return degree / top
