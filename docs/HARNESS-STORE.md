# Content-addressed store foundation

H-05 provides a local Python API, `HarnessStore(root)`, for immutable objects
identified by SHA-256. `put_blob` atomically publishes and deduplicates a bounded
blob; `get_blob` verifies its digest every time. Canonical manifest JSON is
stable regardless of component-map order. `put_manifest` requires every listed
component object to exist and match its hash; `get_manifest` checks the manifest
and every referenced component again. Duplicate JSON keys, malformed paths,
hashes, oversized files and symlinked objects fail closed. The CLI exposes
metadata inspection, but candidate objects are not enabled in server execution.

This is an integrity mechanism, **not authentication or a sandbox against a
hostile local user**. The store root and its parent directories must be trusted;
a user able to rewrite the store or replace an entire hierarchy can delete or
substitute data. Object hashes do not sign provenance. H-06 adds local SQLite refs and lineage metadata: an immutable initial
`refs/heads/adopted` can only name the packaged baseline, candidate refs use
transactional compare-and-set, and append-only parent edges reject cycles.
Resolving a ref rechecks all object hashes. The optional `run.start.harness_ref`
field preserves old event bytes. A headless run explicitly selecting `adopted`
now emits the verified packaged manifest ID in that field; candidate refs still
cannot be selected. The baseline ref is not an approval or adoption mechanism. SQLite task, trajectory and judge
metadata are stored as plaintext, so use a trusted private store directory.

Candidate runtime selection, adoption, locking against hostile local races, git
backing, and the full eight-component set remain future work. `--harness` accepts
only the verified packaged adopted baseline and `harnessing.enabled` remains false.

## Inspection CLI

```bash
arcen harness init
arcen harness doctor
arcen harness diff refs/candidates/example
```

Use `arcen harness --store /trusted/path <command>` to choose another local
store. `init` stores the current packaged baseline and creates its metadata ref;
repeating it is safe for the same baseline. `doctor` opens the existing database
read-only and verifies indexed manifests, components, ref history, DAG integrity
and every object file. It also runs SQLite quick-check and expected-schema
validation on present task, review, campaign, budget and experience databases;
it validates task entries but does not verify every other record or relationships
across those databases. Checks are separate snapshots, not one atomic audit, and
SQLite may use WAL sidecars. `diff` compares a candidate against baseline and
strips terminal control characters. Both inspection commands fail if the store is
missing or corrupt and do not create it. Task and trajectory metadata remain
plaintext local data; protect the store directory.

`arcen harness rollback <ref>` currently **refuses without changing anything**.
There is no enabled adoption/approval gate or candidate ref selection, so
claiming rollback works would be misleading and unsafe. `--harness` accepts
only the verified packaged baseline. A successful `doctor` means these bounded
checks passed; it does not prove full database integrity, evidence authenticity,
authorization, safety or security against a hostile local filesystem user.
