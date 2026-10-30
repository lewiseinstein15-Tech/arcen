# Shared admission budget (experimental)

`SharedBudget` is a small **in-process, opt-in admission counter** for the
experimental reviewed trial and comparison APIs. A separate `DurableBudget`
can persist cooperating admission counters across processes; see
`HARNESS-DURABLE-BUDGET.md`. It is not a campaign runner or
the complete H-17 governor. No adoption or autonomy is enabled.

A trusted caller can pass the same instance to multiple reviewed operations:

```python
from arcen.harness.budget import SharedBudget

budget = SharedBudget(
    max_trials=4,
    max_model_calls=8,
    max_judge_calls=2,
    admission_seconds=120,
)
# Pass budget=budget to run_reviewed_probe, run_reviewed_comparison,
# or compare_reviewed_proposals, alongside their existing required arguments.
print(budget.snapshot())
# To refuse future admissions:
budget.stop()
```

Trial starts, calls made through a bound probe model, and invocations of the
caller-supplied judge callback are atomically reserved and shared across the
participating operations. A failed admitted attempt is not refunded. When a
reservation exceeds its limit, an admission deadline passes, or `stop()` is
called, the instance latches closed. Tool dispatch checks the same latch before
starting. A paired comparison uses two trial admissions; it uses one judge
admission only if it reaches the callback. The existing per-trial model-call cap
still applies independently.

**Important limitations:**

- The argument is optional for compatibility with existing experimental APIs.
  Calls that omit it or use a different instance are not counted. A future
  full campaign runner must require and consistently propagate its own budget.
  The experimental manual campaign requires one SharedBudget instance.
- Counters and the stop flag live in one process, are not durable, and do not
  coordinate across processes or survive restart/resume. The trusted local
  caller can construct another instance or call the provider directly.
- The monotonic time is an **admission cutoff**, not a hard wall-clock runtime
  limit. A model call, judge callback, Git operation, or tool command already
  admitted may continue after stop or expiry. Existing provider/command timeout
  parameters are separate and depend on the provider/runtime honoring them.
- A judge admission counts one callback invocation, not its internal network
  requests. Provider SDK retries, billing, tokens, cached tokens, and USD are
  not metered or capped. Never describe these limits as a spending guarantee.
- No concurrency semaphore, scheduler, kill of in-flight work, task/candidate
  `k` policy, pricing data, durable resume, budget events, convergence or
  canaries exist here. Limits apply only to the named admissions.
- The trial, paired comparison and review records remain experimental. Human
  review flags and local records are attestations, not authenticated approval;
  no ref moves and candidate selection and adoption remain disabled.

Tests exercise real code with mocked provider and Docker boundaries, including
concurrent reservations, failure consumption, stopping, expiry and propagation
through composition. An additional opt-in budgeted paired test needs real
Docker; it was not run in the assistant environment. The user reported the
opt-in budgeted pair passed on Omarchy at `4ecaf6e` with mocked model and judge.
