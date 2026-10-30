# Manually curated experience (experimental)

`ExperienceLibrary` is an offline foundation for H-13, **not an automatic
reflector or completed improvement library**. A trusted Python caller can store
a manually written observation in the existing `MemoryStore` graph, associated
with an approved local paired-review record. It never selects a candidate,
changes the adopted ref, calls a model, or feeds notes into an editor prompt.

```python
from arcen.harness.experience import ExperienceLibrary

# memory is an existing MemoryStore; reviews is an existing ReviewLedger.
library = ExperienceLibrary(memory, reviews)
library.record("test-selection", "Check the failing test before retrying.",
               approved_review_id, reviewed=True)
print(library.render())  # human-facing Markdown; not automatically saved or used
```

Topics are bounded lowercase identifiers; observations are bounded single-line
UTF-8 text. Common secret patterns are rejected, but detection is **not
complete**. Do not put credentials or sensitive task output into memory.
Rendered text escapes HTML and Markdown controls for human display; that does
not make a note safe for an LLM. Treat all notes as untrusted and review them
before any future model exposure.

The ledger must currently contain an `approved` paired review; on recall, the
lesson's IDs and source are rechecked against that record. These records and the
`reviewed=True` flag are unsigned local attestations, not authenticated human
approval or proof of evidence, correctness, improvement, or safety. A caller
who controls the databases or Python process can forge them. No judgment is
automatically converted into a lesson.

For each topic, the existing memory store consolidates an identical observation
and supersedes a different observation while retaining history. Observations
expire from the active view 30 days after creation, even if consolidated, and
are ranked using memory's existing decay score without refreshing their access
time. Expiration hides rather than deletes them. `as_of` is for trusted
historical inspection and must not be used to make expired notes current.
The underlying memory store may archive old facts; archived facts are excluded
from recall even for historical times. No global decay or deletion is triggered
by this library. An inactive/expired note is not automatically purged.

The memory store and review ledger must remain accessible; tampered or missing
review/object data can make recall fail closed. A wall-clock rollback blocks
new writes. The existing `MemoryStore` connection is not a concurrency-safe
multi-writer transaction API; callers must serialize library writes, and the
trusted memory database may contain other unrelated facts. The cap counts non-archived, unsuperseded topics, including expired ones until
archived; it is not a storage quota for historical facts. No campaign resume, automatic
learning, contradiction reasoning, model steering, canaries, adoption, or
cross-task baseline selection is enabled.
