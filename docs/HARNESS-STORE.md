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
substitute data. Object hashes do not sign provenance. Refs, lineage, adoption,
CLI, locking against hostile local races, git backing, and the full eight
component set remain future work. `--harness` continues to reject refs and
`harnessing.enabled` remains false.
