# Static candidate policy review (adoption unavailable)

The offline review layer compares two fully verified stored manifests and their
component hashes. It rejects model-pin changes, changes to policy or registry
metadata, a baseline whose protected components differ from the currently
packaged defaults, unknown editable paths, malformed prompt sets and no-op
candidates. The four prompt files are treated as tier 1; tool guidance is tier
2. Both tiers are **human-review-only for now**. Registry metadata is more
conservatively locked here, although the target architecture lists it in C4.

This is a second check independent of the editor's path allowlist. The result
is a classification for review, not an approval or a security proof. The
`adopt_candidate` entry point always raises `AdoptionUnavailable`; neither this
module nor the existing CLI can change the adopted baseline. A complete policy
engine, application/approval gate, authoritative canary gate, rollback, Governor
and live runtime enforcement remain unimplemented. Experimental manual behavioral
canaries exist (`HARNESS-CANARIES.md`) but cannot authorize adoption. Changing package code or the packaged
manifest itself is outside this local store's trust boundary.
