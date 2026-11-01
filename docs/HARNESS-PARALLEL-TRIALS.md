# Reviewed parallel probes (H-14b, partial)

`arcen.harness.parallel_trials.run_reviewed_parallel_trials` is a Python-only
primitive, **not an autonomous campaign**. An explicitly reviewed call binds the
packaged baseline and 2–5 distinct candidates to one archived Git commit,
prepares every model before admitting any trial, runs the reference once, then
runs candidates in input-ordered waves of 1–4 workers. The Docker-only,
network-none probe boundary remains mandatory. Optional expected snapshot hash
and known-secret checks happen before trials. Results have statuses and
unstarted IDs; no results are selected, judged, saved or adopted.

Use either a `SharedBudget` or a `DurableBudget` with matching explicitly
created `DurableTrialSlots`. A shared budget's lock protects admissions and
optional in-process concurrency slots among cooperating users of the **same
object**. Durable slots persist the cap and occupied slots in a local SQLite
database; separate processes count only if they cooperate by using this same
slot API and budget ID.
The minimum check before the reference is only an instantaneous check, not a
reservation of the whole batch; actual per-call and per-trial admission can
stop subsequent work. Set the budget's concurrency cap separately if sharing
it with other jobs. A failed wave prevents scheduling later waves, but all
already-submitted work is awaited and cannot be canceled by this primitive.
An uncertain executor or scheduler failure stops that budget and returns a
sanitized status. A stop between waves prevents further submissions.

A durable slot is released only after a successful body and cleanup. An
exception retains the slot and makes a best-effort attempt to stop the durable
budget; stopping can fail if its database is unavailable. A killed process can
leave the slot occupied while the budget itself stays open. Slots are never
reclaimed automatically and there is no reset API. An operator must investigate
any orphaned container and use a new budget only after resolving uncertainty.
Existing APIs that don't use these slots are **not** constrained by them.
The filesystem, local SQLite database, same-host participants and Docker daemon
are trusted; database tampering or deletion can bypass accounting. These are
not distributed leases and have not been validated on network filesystems.

This API has no universal concurrency enforcement, hard deadline or in-flight
kill, provider billing cap, fair queue, crash recovery or safe automatic resume. In-flight calls can continue and the wait can be long;
a process crash may lose accounting. Snapshot and model hashes are not trust
or authorization. Secret checks are incomplete, local artifacts and providers
remain untrusted, and the API does not establish improvement or approve a
candidate. Do not use it for unattended recursion or adoption. The user
reported a narrow real-Docker smoke passing at `51d971a`, with provider mocked;
live-provider behavior remains untested. This is not a safety proof. The full
H-14 ticket remains open.
