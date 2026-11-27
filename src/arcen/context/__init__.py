"""Context reuse: caches for computed context, not a KV cache.

GLM-5.4 saves memory by sharing KV state across loop iterations and reusing
the sparse-attention indices the first pass already computed. Both are
*inference-engine* properties: they need access to the model's attention
state, which no hosted chat-completion API exposes.

The transferable principle is "never recompute unchanged information".
Applied to an agent, the recomputed things are:

- rendered context blocks (tool catalog, skills index, memory digest) that
  are rebuilt on every turn although nothing changed;
- retrieval results (search hits, ranked files) recomputed on every
  refinement pass although the corpus did not change;
- identical text blocks stored repeatedly for the same session.

:class:`ContextCache` is content-addressed and deduplicated;
:class:`RetrievalIndex` memoizes retrieval per ``(query, corpus version)``
and is invalidated explicitly when the corpus changes. Neither is a KV
cache and neither claims to save model-side compute — the saving is in
prompt construction and retrieval work, and it is measured.
"""

from arcen.context.cache import ContextCache, fingerprint
from arcen.context.retrieval import RetrievalIndex

__all__ = ["ContextCache", "RetrievalIndex", "fingerprint"]
