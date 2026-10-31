# Manual composition from recorded comparisons (experimental)

`arcen harness campaign compose` lets an operator inspect summaries and diffs
for 2–5 candidates from **one completed local campaign**, then deliberately
combine chosen candidates into an unadopted manifest. It is a manual aid, not
an automatic winner selector, safe-recursion engine, authenticated approval or
adoption gate.

First run a manual campaign with multiple candidates using the same task,
baseline, commit and budget. Use `campaign status CAMPAIGN_ID` to find its
review IDs and `review show REVIEW_ID` to inspect them. Import the exact same
task bytes into the task bank if they are not already there. Then:

```sh
arcen harness --store "$STORE" campaign compose "$CAMPAIGN" \
  --task-id "$TASK_ID" --review "$REVIEW_A" --review "$REVIEW_B"
```

Repeat `--review` for up to five distinct records. The command requires an
interactive terminal and rejects incomplete campaigns, mismatched task hashes,
reviews not linked to that campaign, static or rejected reviews, mismatched
baseline/candidate/commit and inconsistent recorded workspace hashes. It
requires the unchanged packaged baseline. Local `pending` or `approved` review
states are accepted; those labels are **not authenticated approval**. Ties and
losses may be selected deliberately—there is no automatic winner selection.

The command displays the task, recorded outcomes, confidence values and each
candidate diff. These are **unsigned local metadata**: they can be fabricated or
modified by trusted local callers, and the journal/review association is not a
cryptographic proof that trials occurred, used the task, or were judged by a
particular person. Full trajectories are not retained in these records. Inspect
other available evidence independently; an approval label or judge result does
not establish safety or improvement. Secret detection and redaction are
incomplete; displayed text and retained objects may be sensitive.

After exact `COMPOSE CAMPAIGN_ID` confirmation, the command re-reads and
revalidates the local data, reconstructs exact base-relative unified diffs from
the verified component bytes, and invokes the conservative syntactic composer.
The reconstructed diffs do not preserve the original proposal scope or hunk
boundaries. By default overlapping/touching edits are refused without a composite object.
An opt-in manual patch workflow is described below; no more than ten
component-level proposals can be combined. Rechecks are not
an atomic transaction across databases and the filesystem, and do not defend
against a hostile local writer. A storage failure can leave unreferenced objects.
No durable provenance record for the composite is created.

A successful result is a new **untested, unapproved and unadopted** composite;
the command performs no provider call, Docker run, plan, review decision or ref
change. A conflict-free merge does not prove behavioral compatibility or
safety. Inspect the displayed combined diff. If you elect to test it, create a
separate budget-bound campaign plan against the same baseline and task, then
run that plan with the usual explicit confirmation and human judgment:

```sh
arcen harness --store "$STORE" campaign plan --baseline "$BASELINE" \
  --candidate "$COMPOSITE" --task-id "$TASK_ID" \
  --commit "$COMMIT" --budget "$BUDGET"
arcen harness --store "$STORE" campaign run "$NEW_CAMPAIGN" \
  --task-id "$TASK_ID" --config ./arcen.yaml --repo . --budget "$BUDGET"
```

A later test result still cannot authorize adoption. Docker-only fail-closed
isolation, incomplete secret detection, provider exposure and cost warnings,
admission-only budgets, and no automatic resume continue to apply. SHA-256
hashes detect changes, not provenance, and may reveal predictable task text.

## Opt-in local conflict patch workflow

For a conflicting completed campaign, add `--resolve-conflicts` to the command.
After the initial `COMPOSE` confirmation, the CLI lists conflicts and asks for
a local UTF-8 unified-diff file for each conflicting editable path. Patches
must apply exactly to the **campaign baseline**, with the same single-path
headers accepted by the editor. The CLI does not generate the files or run an
editor, model, Docker or shell command. The patch file must be a bounded regular
file, not a final-component symlink or FIFO. Enter `CANCEL` to stop.

Each replacement patch **supersedes all selected proposals for that path**,
including non-conflicting edits. The CLI prints a control-sanitized and
best-effort redacted patch; redaction is incomplete and may hide details.
Inspect the complete file and all retained edits separately. The final `RESOLVE
CAMPAIGN_ID` confirmation is required before creating a candidate. Cancelling
or an invalid patch leaves no composite candidate. The CLI rechecks campaign
metadata after confirmation, but local stores/filesystem are trusted and the
checks are not one atomic transaction. A created candidate remains untested
and unadopted and needs a separate reviewed trial; no approval or ref moves.

```sh
arcen harness --store "$STORE" campaign compose "$CAMPAIGN" \
  --task-id "$TASK_ID" --review "$REVIEW_A" --review "$REVIEW_B" \
  --resolve-conflicts
```
