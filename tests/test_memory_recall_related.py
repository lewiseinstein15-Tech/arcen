"""Memory recall by relatedness — what makes the memory write worth reading.

The turn path wrote a fact every run and never read one back: `recall` needs
an exact entity, and a new goal rarely equals an old one. `recall_related`
closes that loop with lexical overlap, which is explainable and testable.
These pin the ranking, the stopword filter, and the supersede/decay rules
that must still hold.
"""

from __future__ import annotations

import pytest

from arcen.memory.store import MemoryStore


@pytest.fixture()
def store(tmp_path) -> MemoryStore:
    s = MemoryStore(str(tmp_path / "memory.db"), half_life_days=14)
    yield s
    s.close()


def test_related_fact_is_recalled_from_a_different_entity(store) -> None:
    store.write("calc.py:add", "add() returns the sum of two integers", source="turn")
    hits = store.recall_related("please extend calc.py add() to handle negatives")
    assert hits, "a fact about the same file and function must be found"
    assert "sum of two integers" in hits[0]["fact"]
    assert "calc" in hits[0]["overlap"]


def test_shared_file_path_overrides_the_overlap_floor(store) -> None:
    """A goal that names the same file as an earlier turn must recall it.

    "create fizzbuzz.py with fizzbuzz(n)" and a stored fact about
    "fizzbuzz.py" share exactly one token, so the two-token floor used to
    hide the fact even though the path is unambiguous evidence.
    """
    store.write(
        "create fizzbuzz.py with fizzbuzz(n) and test_fizzbuzz.py, then run pytest",
        "turn r-1: 3 steps, verified=True",
        source="turn",
    )
    hits = store.recall_related("create fizzbuzz.py with fizzbuzz(n)", min_overlap=2)
    assert hits, "the same file path must be enough"
    assert "fizzbuzz.py" in hits[0]["overlap"]


def test_single_token_overlap_is_not_enough(store) -> None:
    store.write("unrelated", "the server uses uvicorn", source="turn")
    assert store.recall_related("uvicorn", min_overlap=2) == []


def test_stopwords_do_not_create_relatedness(store) -> None:
    store.write("task", "create a new file and make it", source="turn")
    assert store.recall_related("create a new file and make it") == []


def test_superseded_facts_are_not_recalled(store) -> None:
    store.write("calc.py:add", "add() returns a string", key="signature", source="turn")
    store.write("calc.py:add", "add() returns an integer", key="signature", source="turn")
    facts = [hit["fact"] for hit in store.recall_related("calc.py add() integer")]
    assert "add() returns a string" not in facts


def test_ranking_prefers_more_overlap(store) -> None:
    store.write("calc.py:add", "add() sums two integers", source="turn")
    store.write("notes:calc.py", "calc.py exists but nothing about arithmetic", source="turn")
    hits = store.recall_related("calc.py add() integers", k=2)
    assert hits[0]["entity"] == "calc.py:add"


def test_empty_query_returns_nothing(store) -> None:
    store.write("calc.py:add", "add() sums two integers")
    assert store.recall_related("   ") == []


def test_k_bounds_the_result(store) -> None:
    for index in range(5):
        store.write(f"calc.py:f{index}", f"function f{index} in calc.py parses input")
    assert len(store.recall_related("calc.py parses input", k=2)) == 2
