# Content-addressed store foundation

H-05 provides a local Python API, `HarnessStore(root)`, for immutable objects
identified by SHA-256. `put_blob` atomically publishes and deduplicates a bounded
blob; `get_blob` verifies its digest every time. Canonical manifest JSON is
stable regardless of component-map order. `put_manifest` requires every listed
component object to exist and match its hash; `get_manifest` checks the manifest
and every referenced component again. Duplicate JSON keys, malformed paths,
hashes, oversized files and symlinked objects fail closed. This API is not wired
to server execution or a CLI yet.

This is an integrity mechanism, **not authentication or a sandbox against a
hostile local user**. The store root and its parent directories must be trusted;
a user able to rewrite the store or replace an entire hierarchy can delete or
substitute data. Object hashes do not sign provenance. H-06 adds local SQLite refs and lineage metadata: an immutable initial
`refs/heads/adopted` can only name the packaged baseline, candidate refs use
transactional compare-and-set, and append-only parent edges reject cycles.
Resolving a ref rechecks all object hashes. The optional `run.start.harness_ref`
field round-trips without changing old event bytes, but it is not emitted yet.
These refs do **not** select or execute a harness; the baseline ref is metadata,
not a human approval or adoption mechanism. SQLite task, trajectory and judge
metadata are stored as plaintext, so use a trusted private store directory.

Runtime selection, adoption, CLI, locking against hostile local races, git
backing, and the full eight-component set remain future work. `--harness` continues to reject refs and
`harnessing.enabled` remains false.
