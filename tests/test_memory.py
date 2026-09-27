"""T-016 / Test-plan (memory) — store + graph (BACKEND-SPEC Part 5).

Proves: store fact → recall it; decay archives stale facts; repeated
observations consolidate; conflicts supersede with history; temporal
queries work; recall prioritizes by weight × recency × centrality.
"""

import time

import pytest

from arcen.memory.store import MemoryStore

DAY = 86400.0


@pytest.fixture()
def store(tmp_path) -> MemoryStore:
    s = MemoryStore(str(tmp_path / "memory.db"), half_life_days=14)
    yield s
    s.close()


def test_wal_mode(store) -> None:
    mode = store.conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_store_fact_recall_it(store) -> None:
    # mirrors the ticket Command: store fact, recall it
    out = store.write("calc()", "returns int sum", source="t1")
    assert out["op"] == "new"
    facts = store.recall("calc()")
    assert len(facts) == 1
    assert facts[0]["fact"] == "returns int sum"
    assert facts[0]["sources"] == ["t1"]


def test_consolidation_merges_repeats(store) -> None:
    for i in range(10):
        store.write("tests/", "tests are slow", source=f"turn-{i}")
    facts = store.recall("tests/")
    assert len(facts) == 1  # one fact, not ten
    assert facts[0]["weight"] == 10.0
    assert len(facts[0]["sources"]) == 10
    assert facts[0]["sources"][0] == "turn-0"


def test_conflict_supersedes_keeps_history(store) -> None:
    first = store.write("server", "port is 3002", key="port")
    second = store.write("server", "port is 3003", key="port")
    assert second["op"] == "superseded"
    assert second["superseded"] == first["fact_id"]
    # recall sees only the new truth
    facts = store.recall("server")
    assert [f["fact"] for f in facts] == ["port is 3003"]
    # history keeps both, old one stamped invalid_at
    hist = store.history("server", "port")
    assert [h["fact"] for h in hist] == ["port is 3002", "port is 3003"]
    assert hist[0]["invalid_at"] is not None


def test_temporal_validity_as_of(store) -> None:
    t0 = time.time()
    store.write("server", "port is 3002", key="port", ts=t0)
    t1 = t0 + 10
    store.write("server", "port is 3003", key="port", ts=t1)
    # as of t0 + 5 the world believed port 3002
    past = store.recall("server", as_of=t0 + 5, touch=False)
    assert [f["fact"] for f in past] == ["port is 3002"]
    now = store.recall("server", as_of=t1 + 5, touch=False)
    assert [f["fact"] for f in now] == ["port is 3003"]


def test_decay_archives_but_never_deletes(store) -> None:
    store.write("deploy", "deploy script is scripts/deploy.sh", key="deploy script")
    # 90 days of silence with a 14-day half-life → weight 1.0 → 1 * 0.5^(90/14) ≈ 0.0116 < 0.1
    result = store.decay(now=time.time() + 90 * DAY)
    assert result["archived"] == 1
    facts = store.recall("deploy", touch=False)
    assert facts == []  # gone from active recall
    # but the row survives — history is never deleted
    hist = store.history("deploy", "deploy script")
    assert len(hist) == 1 and hist[0]["archived"] == 1


def test_decay_uses_half_life(store) -> None:
    fast = MemoryStore(store.path + ".fast", half_life_days=1)
    try:
        fast.write("x", "fresh fact", ts=time.time())
        # 5 days with 1-day half-life → 1 * 0.5^5 = 0.03125 < 0.1 → archived
        assert fast.decay(now=time.time() + 5 * DAY)["archived"] == 1
    finally:
        fast.close()


def test_recall_prioritization_ranking(store) -> None:
    store.graph.relate("anthropic", "claude", "provider-of")  # connected entity
    for _ in range(3):
        store.write("anthropic", "makes claude")
    store.write("randolith", "old weak fact")
    ranked = store.recall("anthropic")
    assert ranked[0]["fact"] == "makes claude"
    # k caps the prompt budget
    for i in range(20):
        store.write("calc()", f"fact number {i}", key=f"k{i}")
    assert len(store.recall("calc()", k=5)) == 5


def test_recall_updates_last_accessed(store) -> None:
    store.write("x", "the fact")
    before = store.recall("x")[0]["score"]
    time.sleep(0.01)
    store.recall("x")
    after = store.recall("x", touch=False)[0]["score"]
    # access refreshes recency — the fact decays slower
    assert after >= before


def test_forget_archives(store) -> None:
    out = store.write("x", "to be forgotten")
    store.forget(out["fact_id"])
    assert store.recall("x") == []
    assert store.history("x", "to be forgotten")[0]["archived"] == 1


def test_graph_centrality_and_neighbors(store) -> None:
    store.graph.relate("calc()", "tests/test_pay.py", "tested-by")
    store.graph.relate("calc()", "arith", "part-of")
    assert store.graph.centrality("calc()") == 1.0  # highest degree
    assert store.graph.centrality("isolated") == 0.0
    neighbors = {n["neighbor"] for n in store.graph.neighbors("calc()")}
    assert neighbors == {"tests/test_pay.py", "arith"}


def test_main_demo() -> None:
    from arcen.memory import store as store_mod

    assert store_mod.main([]) == 0
