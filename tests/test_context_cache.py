"""Context reuse: cached blocks and memoized retrieval, with real invalidation.

The risk with a cache is serving something stale. These tests pin both
halves: the saving is real (a second render does not happen) and the
invalidation is real (a changed version is a different key, and a bumped
corpus drops every memoized ranking).
"""

from __future__ import annotations

import pytest

from arcen.context import ContextCache, RetrievalIndex, fingerprint

# -- fingerprint ------------------------------------------------------------


def test_fingerprint_is_stable_and_order_sensitive() -> None:
    assert fingerprint("a", 1) == fingerprint("a", 1)
    assert fingerprint("a", 1) != fingerprint(1, "a")


def test_fingerprint_ignores_nothing_relevant() -> None:
    assert fingerprint("catalog", ("bash", "read")) != fingerprint("catalog", ("bash",))


# -- cache ------------------------------------------------------------------


def test_cache_computes_once_then_reuses() -> None:
    cache = ContextCache()
    calls = []

    def compute() -> str:
        calls.append(1)
        return "catalog body"

    assert cache.get_or_compute("brief:v1", compute) == "catalog body"
    assert cache.get_or_compute("brief:v1", compute) == "catalog body"
    assert len(calls) == 1
    assert cache.stats()["hits"] == 1


def test_cache_miss_is_a_miss() -> None:
    cache = ContextCache()
    assert cache.get("never") is None
    assert cache.stats()["misses"] == 1


def test_a_new_version_is_a_new_key() -> None:
    cache = ContextCache()
    cache.put("brief:" + fingerprint(("bash",)), "old")
    fresh = cache.get("brief:" + fingerprint(("bash", "read")))
    assert fresh is None


def test_identical_text_is_stored_once() -> None:
    cache = ContextCache()
    body = "x" * 1000
    cache.put("a", body)
    cache.put("b", body)
    stats = cache.stats()
    assert stats["blocks"] == 1
    assert stats["dedup_hits"] == 1
    assert stats["bytes_avoided"] >= 1000
    assert cache.get("b") == body


def test_invalidate_by_prefix_drops_only_that_prefix() -> None:
    cache = ContextCache()
    cache.put("brief:1", "brief")
    cache.put("skills:1", "skills")
    assert cache.invalidate("brief:") == 1
    assert cache.get("brief:1") is None
    assert cache.get("skills:1") == "skills"


def test_lru_eviction_bounds_entries() -> None:
    cache = ContextCache(max_entries=2)
    cache.put("a", "1")
    cache.put("b", "2")
    cache.put("c", "3")
    assert cache.get("a") is None
    assert cache.get("c") == "3"


def test_byte_budget_evicts() -> None:
    cache = ContextCache(max_entries=100, max_bytes=2048)
    cache.put("big", "x" * 1500)
    cache.put("big2", "y" * 1500)
    assert cache.stats()["bytes_stored"] <= 2048


def test_cache_rejects_impossible_limits() -> None:
    with pytest.raises(ValueError):
        ContextCache(max_entries=0)
    with pytest.raises(ValueError):
        ContextCache(max_bytes=10)


# -- retrieval --------------------------------------------------------------


def test_retrieval_scorer_runs_once_per_query() -> None:
    index = RetrievalIndex()
    calls = []

    def scorer():
        calls.append(1)
        return ["a.py", "b.py"]

    assert index.search("parse the config", scorer=scorer) == ["a.py", "b.py"]
    assert index.search("Parse   the CONFIG", scorer=scorer) == ["a.py", "b.py"]
    assert len(calls) == 1
    assert index.stats()["reused_results"] == 2


def test_bump_invalidates_every_ranking() -> None:
    index = RetrievalIndex()
    index.search("q", scorer=lambda: ["old"])
    index.bump()
    assert index.search("q", scorer=lambda: ["new"]) == ["new"]


def test_limit_truncates_without_recomputing() -> None:
    index = RetrievalIndex()
    calls = []
    index.search("q", scorer=lambda: calls.append(1) or ["a", "b", "c"])
    assert index.search("q", scorer=lambda: calls.append(1) or [], limit=2) == ["a", "b"]
    assert len(calls) == 1


def test_results_are_copies() -> None:
    index = RetrievalIndex()
    first = index.search("q", scorer=lambda: ["a"])
    first.append("mutated")
    assert index.search("q", scorer=lambda: ["a"]) == ["a"]
