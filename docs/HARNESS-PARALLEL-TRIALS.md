# Reviewed parallel probes (H-14b, partial)

`arcen.harness.parallel_trials.run_reviewed_parallel_trials` is a Python-only
primitive, **not an autonomous campaign**. An explicitly reviewed call binds the
packaged baseline and 2–5 distinct candidates to one archived Git commit,
prepares every model before admitting any trial, runs the reference once, then
runs candidates in input-ordered waves of 1–4 workers. The Docker-only,
network-none probe boundary remains mandatory. Optional expected snapshot hash
and known-secret checks happen before trials. Results have statuses and
unstarted IDs; no results are selected, judged, saved or adopted.

A shared `SharedBudget` is mandatory. Its lock protects admissions and optional
in-process concurrency slots among cooperating users of the **same object**.
The minimum check before the reference is only an instantaneous check, not a
reservation of the whole batch; actual per-call and per-trial admission can
stop subsequent work. Set the budget's concurrency cap separately if sharing
it with other jobs. A failed wave prevents scheduling later waves, but all
already-submitted work is awaited and cannot be canceled by this primitive.
An uncertain executor or scheduler failure stops that budget and returns a
sanitized status. A stop between waves prevents further submissions.

This API has no durable or cross-process accounting, no hard deadline or
in-flight kill, no provider billing cap, no fair queue, no crash recovery or
safe automatic resume. In-flight calls can continue and the wait can be long;
a process crash may lose accounting. Snapshot and model hashes are not trust
or authorization. Secret checks are incomplete, local artifacts and providers
remain untrusted, and the API does not establish improvement or approve a
candidate. Do not use it for unattended recursion or adoption. Real Docker and
live-provider behavior of this parallel path have not been verified; tests
mock both boundaries. The full H-14 ticket remains open.
