# Durable admission accounting (experimental)

`DurableBudget` extends the experimental reviewed trial and manual comparison
APIs with SQLite-backed admission counts. Cooperating processes that open the
same budget ID in the same trusted store share atomic counters and a persistent
stop flag. Reservations are made before a trial, probe model call or judge
callback begins; admitted attempts are never refunded on failure.

```python
from arcen.harness.durable_budget import DurableBudget

# store is an existing HarnessStore; reuse the same object in the trial APIs.
limits = DurableBudget.create(store, max_trials=3, max_model_calls=6,
                              max_judge_calls=2, admission_seconds=120)
print(limits.id)
# Pass budget=limits to the reviewed probe, comparison, proposal comparison,
# or manual campaign APIs. A later trusted process can reopen the same ID:
reopened = DurableBudget(store, limits.id)
print(reopened.snapshot())
```

For an initialized store, another terminal may inspect or stop a budget:

```sh
arcen harness --store /path/to/store budget status BUDGET_ID
arcen harness --store /path/to/store budget stop BUDGET_ID
```

Stopping prevents future admissions by cooperating participants. Already
admitted Git, model, judge, container and tool work may finish. The timeout is
an **admission cutoff**, not a hard wall-clock deadline. Wall-clock rollback
between operations latches the budget closed; deadlines and counters survive a
process restart. The trusted database, local clock and filesystem must not be
altered or rolled back; the database is not signed and its owner can modify it.
A newly created file uses owner-only permissions.

This does **not** cap tokens, USD, retries inside provider SDKs, or requests
made within the judge callback. It does not limit nonparticipating callers or
a caller that creates a new budget ID. Campaign journal records do not yet bind
or persist a budget ID; automatic resume remains disabled, because an earlier
external action may have completed before a crash. There is no scheduler,
concurrency semaphore, in-flight cancellation, provider price guarantee, canary
or adoption gate. The existing `SharedBudget` remains available as an
in-process alternative. The assistant environment could not run Docker; the
user reported the opt-in real-Docker test passed on Omarchy at `4ecaf6e` with
mocked model responses and judge. See `HARNESS-CAMPAIGN-JOURNAL.md` and
`HARNESS-MANUAL-CAMPAIGN.md`.
