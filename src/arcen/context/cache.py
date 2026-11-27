"""Content-addressed cache for rendered context blocks.

Two savings, both measurable:

- **reuse** — a key already computed (same registry, same skills, same
  workspace note) returns the stored text instead of re-rendering it;
- **dedup** — identical text stored under different keys is held once, so
  a catalog repeated across a session costs one copy, not N.

Invalidation is explicit and versioned: callers pass a version into the
key (:func:`fingerprint`), so a changed registry or skill index produces a
different key and the stale entry is evicted by LRU rather than served.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from collections.abc import Callable


def fingerprint(*parts: object) -> str:
    """A stable short hash of the inputs that decide a block's content."""
    digest = hashlib.sha256()
    for part in parts:
        digest.update(repr(part).encode("utf-8", "replace"))
        digest.update(b"\x00")
    return digest.hexdigest()[:16]


class ContextCache:
    """Bounded LRU of text blocks, keyed by purpose and content version."""

    def __init__(self, *, max_entries: int = 256, max_bytes: int = 4 * 1024 * 1024) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        if max_bytes < 1024:
            raise ValueError("max_bytes must be >= 1024")
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        # key -> digest; digest -> text (the dedup layer)
        self._keys: OrderedDict[str, str] = OrderedDict()
        self._blocks: dict[str, tuple[str, int]] = {}
        self._bytes = 0
        self._hits = 0
        self._misses = 0
        self._dedup_hits = 0
        self._bytes_avoided = 0

    # -- reads -------------------------------------------------------------
    def get(self, key: str) -> str | None:
        digest = self._keys.get(key)
        if digest is None:
            self._misses += 1
            return None
        self._keys.move_to_end(key)
        self._hits += 1
        return self._blocks[digest][0]

    def get_or_compute(self, key: str, compute: Callable[[], str]) -> str:
        """Return the cached block, or compute and store it."""
        cached = self.get(key)
        if cached is not None:
            return cached
        value = compute()
        self.put(key, value)
        return value

    # -- writes ------------------------------------------------------------
    def put(self, key: str, text: str) -> None:
        digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
        if key in self._keys and self._keys[key] == digest:
            self._keys.move_to_end(key)
            return
        if digest in self._blocks:
            # identical text already stored — point at it, do not copy
            self._dedup_hits += 1
            self._bytes_avoided += len(text.encode("utf-8"))
            self._drop_key(key)
            self._keys[key] = digest
        else:
            size = len(text.encode("utf-8"))
            self._blocks[digest] = (text, size)
            self._bytes += size
            self._drop_key(key)
            self._keys[key] = digest
        self._evict()

    def invalidate(self, prefix: str = "") -> int:
        """Drop every key starting with ``prefix``. Returns how many went."""
        victims = [k for k in self._keys if k.startswith(prefix)]
        for key in victims:
            self._drop_key(key)
        self._evict()
        return len(victims)

    # -- internals ---------------------------------------------------------
    def _drop_key(self, key: str) -> None:
        digest = self._keys.pop(key, None)
        if digest is not None and digest not in self._keys.values():
            block = self._blocks.pop(digest, None)
            if block is not None:
                self._bytes -= block[1]

    def _evict(self) -> None:
        while self._keys and (
            len(self._keys) > self.max_entries or self._bytes > self.max_bytes
        ):
            oldest = next(iter(self._keys))
            self._drop_key(oldest)

    # -- reporting ---------------------------------------------------------
    def stats(self) -> dict:
        lookups = self._hits + self._misses
        return {
            "entries": len(self._keys),
            "blocks": len(self._blocks),
            "bytes_stored": self._bytes,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / lookups, 3) if lookups else 0.0,
            "dedup_hits": self._dedup_hits,
            "bytes_avoided": self._bytes_avoided,
        }
