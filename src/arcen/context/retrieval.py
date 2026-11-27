"""Retrieval results memoized per ``(query, corpus version)``.

The analogue of sparse-attention index reuse: GLM-5.4's second loop pass
reuses the indices the first pass computed instead of re-indexing, because
the context has not changed between passes. Here the "index" is whatever
ranks candidate context — a regex search, a memory query, a file ranking —
and the same rule applies: if the query and the corpus are unchanged, the
ranking is unchanged, so do not pay for it twice.

Invalidation is explicit. A caller that changes the corpus calls
:meth:`RetrievalIndex.bump` (or passes a new version), which drops every
memoized result. Serving a stale ranking is worse than recomputing it.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Iterable
from typing import Any


class RetrievalIndex:
    """Memoized retrieval with an explicit corpus version."""

    def __init__(self, *, max_entries: int = 128, version: int = 0) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self.max_entries = max_entries
        self.version = version
        self._memo: OrderedDict[tuple[str, int], list[Any]] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._reused_results = 0

    def search(
        self,
        query: str,
        *,
        scorer: Callable[[], Iterable[Any]],
        limit: int | None = None,
    ) -> list[Any]:
        """Return ranked results for ``query``, reusing the memo when valid.

        ``scorer`` is only called on a miss — that is the whole point: an
        unchanged query over an unchanged corpus costs nothing after the
        first pass.
        """
        key = (" ".join(query.lower().split()), self.version)
        cached = self._memo.get(key)
        if cached is not None:
            self._hits += 1
            self._reused_results += len(cached)
            self._memo.move_to_end(key)
            return list(cached[:limit] if limit is not None else cached)

        self._misses += 1
        results = list(scorer())
        self._memo[key] = results
        while len(self._memo) > self.max_entries:
            self._memo.popitem(last=False)
        return list(results[:limit] if limit is not None else results)

    def bump(self) -> int:
        """The corpus changed: drop every memoized ranking."""
        self.version += 1
        dropped = len(self._memo)
        self._memo.clear()
        return dropped

    def stats(self) -> dict:
        lookups = self._hits + self._misses
        return {
            "version": self.version,
            "entries": len(self._memo),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / lookups, 3) if lookups else 0.0,
            "reused_results": self._reused_results,
        }
