# Manual sequential candidate comparisons (experimental)

`run_manual_campaign` is an explicitly invoked **trusted Python API**, not a
complete H-11 campaign runner. A caller supplies one to five distinct stored
candidate manifest IDs; it does not generate or choose candidates. Before
calling it, review the baseline, every candidate, task, Git commit, model
provider and judge-data exposure. Both `reviewed_inputs=True` and
`reviewed_judge_inputs=True` are caller attestations, not verified human consent.
Calls may transmit data to the configured provider and judge and incur costs.

The function validates every candidate and freezes all provider bindings before
snapshotting Git or starting a trial. It captures the selected commit once, runs
one baseline trial, then runs candidates sequentially in fresh Docker-only
containers from that same verified archive. Each successful candidate is paired
with the **same baseline trajectory**, judged via the existing reduced/blinded
callback, and written as a **pending** review record. The result contains these
completed comparisons and records. It never selects a winner, approves a
review, moves a ref, enables candidate selection or adopts. A baseline need not
be the currently adopted one; later gates must independently verify freshness.

A shared in-process `SharedBudget` and a `ReviewLedger` for the same store are
mandatory. The budget reserves a trial per container, a call per bound probe
model invocation and a callback admission per judge invocation; the baseline is
one trial, and each candidate is another. The ledger must already be open. For
example, with existing, explicitly reviewed `store`, `baseline`, `candidates`,
`task`, `config`, `judge`, `repository`, `commit` and `reviews`:

```python
from arcen.harness.budget import SharedBudget
from arcen.harness.manual_campaign import run_manual_campaign

limits = SharedBudget(max_trials=3, max_model_calls=12,
                      max_judge_calls=2, admission_seconds=120)
result = run_manual_campaign(
    store, baseline, candidates, task, config, judge,
    repo=repository, commit=commit, reviews=reviews, budget=limits,
    reviewed_inputs=True, reviewed_judge_inputs=True,
)
for item in result.completed:
    print(item.candidate_id, item.review.id, item.review.state)
print(result.stop_reason, result.stopped_candidate, limits.snapshot())
```

The local human can inspect pending records with `arcen harness review show` and
record a review decision using the interactive CLI. The decision is unsigned
and **does not authorize adoption**; see `HARNESS-REVIEW.md`.

On a recognized reference, candidate, judge, budget or ledger failure, the
function stops without running further candidates. Unexpected exceptions may
propagate; callers must still inspect any earlier pending records. It returns already-completed items and a
generic `stop_reason`, avoiding callback/provider exception text. Prior pending
records remain. An existing pending review for a pair can cause a ledger failure
*after* trials have run; no automatic retry occurs. An error during or after a
database write can leave a record that must be inspected manually. Preflight
errors and snapshot failures raise instead of returning a result. Abrupt process
termination can leave partial records or a Docker container requiring manual
inspection; optional durable metadata checkpoints are available, but there is no
safe automatic resume. See `HARNESS-CAMPAIGN-JOURNAL.md`.

The admission budget is not a token or USD cap, a hard wall-clock timeout, a
cross-process limit, or an in-flight cancellation mechanism. The judge callback
may make additional unmetered requests. Existing output filtering and blinding
are best effort: the judge sees the same reference evidence repeatedly and may
infer ordering or provenance. Git snapshots and outputs can contain undetected
secrets. The Docker daemon, image, local caller, ledger and store are trusted.

The CLI can inspect or request a stop for journaled runs, but cannot start or
resume them. There is no parallel/sequential recursion, automatic editor,
resume, canary gate, authenticated approval, verifier fusion, spending governor,
or adoption/rollback here. The standard `run_probe` remains blocked. See
`HARNESS-BUDGET.md`, `HARNESS-PROBE.md`, and `HARNESS-COMPARISON.md`.
