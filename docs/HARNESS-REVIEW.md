# Local review ledger (experimental)

This is a **review-record foundation**, not an adoption or authorization gate.
Records are stored in `reviews.sqlite3` in the trusted local harness store.
A newly created file uses owner-only permissions. An approval records a local
reviewer's stated opinion; it never changes a ref, enables candidate selection
or authorizes execution. The judge's verdict is not human approval.

The ledger and local Python caller are trusted. Neither reviewer labels nor
paired results are signed or authenticated. A Python caller can fabricate a
`ReviewedComparison`, `saw_diff=True`, or a reviewer label, and an owner can
modify the database. The database stores only the comparison identifiers,
workspace digest and judge result—not the full trajectories or independent
proof that they ran. Local records may contain sensitive notes; don't put
secrets in them or in command-line arguments. Protect the store and backups.

## Static review

After initializing a store and storing a distinct, policy-valid candidate:

```sh
arcen harness --store /path/to/store review open BASELINE_MANIFEST_ID CANDIDATE_MANIFEST_ID
arcen harness --store /path/to/store review list
arcen harness --store /path/to/store review show REVIEW_ID
arcen harness --store /path/to/store review reject REVIEW_ID --reviewer your-name
```

A static request can be rejected but **cannot be approved**: it has no paired
evidence. `show` prints the sanitized component diff and flags a baseline that
is not currently adopted. Control characters are replaced for terminal safety,
so the display is not a byte-for-byte representation. Large diffs fail closed.
Inspect underlying objects separately where byte-level review matters.

## Paired review

From trusted Python, after the separately reviewed experimental comparison
returns a successful result, record it with:

```python
from arcen.harness.review import ReviewLedger

ledger = ReviewLedger(store, create=True)
record = ledger.request_from_comparison(comparison_result)
print(record.id)
```

`store` and `comparison_result` are the existing store and result from
`run_reviewed_comparison` or `compare_reviewed_proposals` (the latter's
comparison result). Both trials must have successful terminal events and share
the same baseline, commit and workspace digest. The stored judge winner may be
reference, candidate **or tie**; none automatically triggers a decision. A
static and paired request for the same manifests may coexist. A second pending
request of the same type is refused.

Inspect with `review show REVIEW_ID`, then, only if appropriate, run:

```sh
arcen harness --store /path/to/store review approve REVIEW_ID --reviewer your-name
# or: review reject REVIEW_ID --reviewer your-name
```

Both decisions require interactive stdin and stdout; the CLI displays the
sanitized diff and requires the exact `APPROVE REVIEW_ID` or `REJECT REVIEW_ID`
confirmation. There is no `--yes`. This is a local friction mechanism, not
identity verification or proof that a person read every displayed line. If a
record changes after display, the CLI refuses the decision. The Python API's
`saw_diff` flag is only a caller attestation. Decisions use pending-only
compare-and-set semantics; wall-clock rollback is handled by clamping the
recorded decision time to its creation time.

Paired execution is available as a trusted Python API, not a campaign CLI.
The user reported the opt-in trial and paired-comparison real-Docker tests passed
on Omarchy at `f34ea27`, with mocked provider responses and a callback judge.
Before any future adoption mechanism is enabled, it must
independently revalidate the active baseline, actual evidence and authorized
human, immutable policy, canaries, budgets and rollback. This ledger alone does
none of those things; stale-baseline reviews are possible and are flagged in the
CLI, but they remain non-authoritative.
