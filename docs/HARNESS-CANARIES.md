# Experimental manual behavioral canaries

This is an early **manual regression check**, not completion of H-16, a security
proof, an adoption gate or auto-rollback. It runs two small, public fixed tasks
with fixed byte-level artifact checks: write `42` plus a newline, and write the
SHA-256 digest of `abc` plus a newline. They measure narrow task performance,
not prompt-injection resistance, tool security, model alignment or general
correctness. A model that knows the tasks can game them. Neither success nor
failure automatically changes a ref or approves a candidate.

Inspect the two public task descriptions with `arcen harness canary list`.
Given a separately prepared fixed-model packaged baseline, unadopted candidate,
provider configuration, reviewed repository commit and durable budget:

```sh
arcen harness --store "$STORE" canary run \
  --baseline "$BASELINE" --candidate "$CANDIDATE" \
  --config ./arcen.yaml --repo . --commit "$(git rev-parse HEAD)" \
  --budget "$BUDGET"
```

The command requires a terminal, displays the task descriptions and expected
bytes, sanitized candidate diff, provider host, commit, budget usage and limits,
and asks for `CANARY CANDIDATE_ID`. It does not display the full config,
endpoint or repository contents; inspect those independently. No Git snapshot,
model request or container is initiated before confirmation. Confirmation is
not authenticated identity or proof of review. The provider can incur costs
and may receive repository data through tool results. Redaction is best effort.

The operator-created durable budget can allow up to four trials and sixteen
probe-model calls for the two cases; actual usage depends on planning and early
stops. Before snapshot or trial work, the API requires momentary availability of
four trial and four model-call admissions. The CLI checks this before asking
for confirmation and the API checks again after confirmation. A shortfall
raises a budget error without starting trials; it does not reserve capacity or
close an otherwise open budget. It may also reject a run that could have
stopped after an early baseline failure. Sufficient minimum capacity does **not**
guarantee completion: each trial may use more than one model call, and another
consumer may use capacity after the check. Limits count admissions, not tokens,
USD, an in-flight deadline, or requests made by noncooperating processes. Stop
and timeout do not cancel already admitted work. Snapshot or preflight errors
raise without a canary report; provider, Docker and budget failures during the
trials yield **inconclusive**. A budget may close at any time after the preview.

The Git commit is snapshotted once. Each baseline or candidate trial runs in a
fresh Docker container from that same snapshot, with network disabled and no
host fallback. Inside each disposable workspace the fixed output path is first
removed; if it was a directory or removal failed, the trial is inconclusive.
After the model's normal bounded probe, a fixed verifier opens the final output
path with Linux no-follow and nonblocking flags, then checks that same file
descriptor is regular, has the exact size and contains the expected bytes.
This prevents the final path being swapped to a symlink between an `lstat` and
an ordinary open. A FIFO cannot block the verifier; missing required flags yield
an inconclusive verifier error. Parent path safety and immutable contents are
not established: hard links or a process with shared filesystem access can
still interfere. Container cleanup must succeed before any result is accepted.
The model sees the public task; the verifier is code-defined but runs in the
same container as model-generated commands. A malicious process or compromised
image/daemon can interfere with it. The normal probe's TEMPER check may rerun
the model's last command.

For each case, a baseline error or failure yields **inconclusive** and stops.
If the baseline passes but the candidate fails, the report is **regression**
and stops. Infrastructure errors, malformed verifier results and budget
exhaustion are inconclusive, not regression or success. A result with a
mismatched baseline, candidate, commit, workspace or terminal status is also
inconclusive. This is a local consistency check, not authenticated evidence or
proof that the intended case ran. Only when both pass
both cases is the report **passed**. Output is ephemeral and unsigned; no
journal, authenticated evidence, persistent canary history or acceptance gate
is produced. Existing Python callers and local databases are trusted and can
fabricate or alter evidence. A passing result is not a reason to bypass human
review or activate a candidate.

Automated tests run the verifier logic on local temporary files and exercise the
orchestrator with mocked Docker and model responses. An opt-in real-Docker test
exists but could not be run in the assistant sandbox; earlier user-reported
Docker tests did not cover this new feature. No real external model was tested.
