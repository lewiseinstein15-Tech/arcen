# Advisory review and canary fusion (experimental H-18a)

The manual canary CLI can optionally compare its fresh result with an existing
local paired review:

```sh
arcen harness --store "$STORE" canary run \
  --baseline "$BASELINE" --candidate "$CANDIDATE" --review "$REVIEW_ID" \
  --config ./arcen.yaml --repo . --commit "$COMMIT" --budget "$BUDGET"
```

This is **advisory only**, not an adoption gate. It requires the normal terminal
confirmation and performs the normal paid-provider and Docker operations. The
review's baseline, candidate and commit must match the supplied inputs; after
confirmation, the Git snapshot hash must match the recorded paired comparison
before any trial is admitted or provider or Docker is called. The review must
remain unchanged while the canaries run. No record, ref or approval is changed
by this advisory. The operator must separately verify the current active
baseline; this feature does not establish freshness.

The pure Python `arcen.harness.fusion.assess` API combines a `ReviewRecord` and
`CanaryReport`, checking that identities, workspace hash, outcome and ordered
findings are structurally consistent. Its ordering is:

1. A canary regression recommends keeping the baseline; inconclusive canaries
   require human attention regardless of other opinions.
2. With passing canaries, a local rejection recommends the baseline; a local
   approval suggests **further review**, never adoption.
3. For a pending review, comparison confidence below 0.8 requires human review.
   With higher confidence, reference or tie recommends the baseline; a candidate
   preference still requires a human. The threshold is a configurable heuristic,
   not a calibrated probability. The interactive human A/B judge's stored 0.5
   is explicitly a placeholder, not assessed confidence.

All outputs have `adoption_authorized=False`. The two canaries are public and
easy to game; their check runs in the model's container. Reviews, reviewer
labels, judgments and reports are unsigned and locally forgeable; matching
hashes do not authenticate origin. The pure API accepts caller-supplied objects
and is not a security boundary. A passing advisory does not prove safety,
improvement, a complete policy check, authorized human approval or eligibility
for runtime selection. No autonomous selection, approval or rollback is enabled.
H-16 and H-18 remain open.
