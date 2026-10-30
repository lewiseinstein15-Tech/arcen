# Guided manual workflow (experimental)

`arcen harness workflow run` connects the existing editor, journal, Docker
comparison, human A/B judge and pending review in one terminal. It runs only
when initiated by a human in a terminal; it does **not** automatically select,
approve, adopt, roll back or resume anything. Human input is not authenticated.
It is not a complete Harness² recursion or safety gate.

Prepare an initialized trusted harness store, a pinned packaged baseline, a
stored task ID, a reviewed Git repository and full commit ID, an ARCEN provider
configuration, and a durable budget. See `HARNESS-TASK-BANK.md`,
`HARNESS-EDITOR.md` and `HARNESS-MANUAL-CLI.md` for preparation and risks.

```sh
arcen harness --store "$STORE" workflow run \
  --baseline "$BASELINE" --task-id "$TASK_ID" --config ./arcen.yaml \
  --repo . --commit "$(git rev-parse HEAD)" --budget "$BUDGET" --k 1
```

The workflow requires a stored task ID, not a mutable task file, and supports
one selected candidate per comparison. It preflights a bounded local Git
snapshot before editor calls, prints its hash, and rechecks the task object at
later stages. The campaign takes a **new** snapshot after its confirmation;
the preliminary hash is neither authenticated nor transactionally bound to
that later snapshot. Inspect the exact commit and data before proceeding.

1. Review the task, model, endpoint and cost/exposure warning. Type the exact
   `EDIT` confirmation to send the task and editable baseline components to the
   provider. Generated diffs are untrusted. `k` is 1–4, generating up to `2*k`
   independent proposals; malformed responses can fail the step. Identical
   resulting candidate IDs are shown only once in the selection list.
2. Inspect the displayed diffs and type `SELECT` plus one full generated
   candidate ID. This chooses a comparison target, **not** a winner or approval.
   Cancelling leaves any generated objects on disk but creates no new plan.
3. The workflow records a budget-bound campaign plan and prints its ID. Review
   the newly displayed task, baseline, candidate diff, provider, repository,
   commit and budget. Only the separate exact `RUN` confirmation starts trials.
   Docker is mandatory with no host-process fallback. Committed files and tool
   output can contain secrets and may be sent to the provider.
4. The human chooses A, B or TIE on reduced, blinded evidence. The workflow
   creates a pending review, not an adoption. Inspect it separately:

   ```sh
   arcen harness --store "$STORE" review show "$REVIEW_ID"
   ```

The command requires at least two trial, one judge and `2*k + 2` model-call
admissions remaining at the initial check. This is only a lower bound, not a
reservation or guarantee of completion: trials may need more calls, a cutoff or
stop may occur, and other cooperating processes may consume admissions. There
is no USD/token cap, hard in-flight cancellation or provider billing guarantee.

After cancellation or failure, inspect the printed campaign ID (if created),
`campaign status`, budget and any pending reviews. A cancelled pre-run plan
may remain ready; after an uncertain or failed run **do not automatically
resume or retry external side effects**. Editor calls may already have incurred
charges, and partial results or unreferenced objects can remain. Tasks are
plaintext, secret detection/redaction is incomplete, and local filesystem,
SQLite, Git, Docker daemon and operator are trusted. Provider and model output,
repository content and instructions are untrusted. No prompt-injection
protection, authenticated approval, comprehensive safety check or authority to
adopt is implied by a completed comparison or review.
