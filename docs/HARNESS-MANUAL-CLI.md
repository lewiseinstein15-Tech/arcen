# Experimental interactive manual campaigns

This is a limited operator-driven comparison, **not the complete Harness²
runner**. It imports locally authored patches or generates unadopted proposals
through a separate confirmed editor command, compares selected candidates to an
unchanged packaged baseline, and records pending reviews. It does not
select, adopt, roll back, resume or run unattended. Docker isolation remains
mandatory and fail-closed; there is no host fallback.

## Prepare

Use a trusted, initialized store and inspect the repository's exact committed
tree, task, patch, provider configuration and endpoint before running. A Git
snapshot can contain secrets and may be sent to the configured provider as the
model uses tools. The model can run commands inside disposable containers.
The provider can charge money. Protect the store, repository and config file.

The CLI's config is a YAML file with the existing ARCEN configuration schema;
`provider.name`, `provider.model`, `provider.base_url` and `provider.api_key`
must match your intended provider and fixed pin. Environment references in the
provider endpoint and key are resolved as in the reviewed probe; do not put
credentials in command-line arguments. Unlike the normal config loader, this
CLI does not seed environment variables from the config. Its stricter YAML
parser rejects duplicate or non-string keys, aliases, anchors, merge keys and
explicit tags to avoid ambiguous or expansive input; use ordinary mappings
instead. Config, task and patch inputs must be bounded UTF-8 regular files; the
final path component cannot be a symlink. Parent directories and the local
filesystem remain trusted.

The following is a workflow outline; replace values with your reviewed inputs.
In a source checkout, `src/arcen/prompts/draft.md` is one possible original for
an editable component. An imported patch must be an exact unified diff for one
allowlisted component, with matching `a/` and `b/` paths; edits to immutable
policy are rejected. The example presumes you have already created and reviewed
such a patch and a task text file. Alternatively, see `HARNESS-EDITOR.md` for
the separately confirmed model-backed proposal command, and
`HARNESS-TASK-BANK.md` for optional stored task IDs.

```sh
STORE="$HOME/.arcen/harness"
arcen harness --store "$STORE" init
arcen harness --store "$STORE" pin-baseline 'fixed:PROVIDER:MODEL'
# Copy printed baseline ID into BASELINE; use the real provider/model in lower-case
# where required by the pin format, matching your config exactly.
arcen harness --store "$STORE" import-patch "$BASELINE" prompts/draft.md ./candidate.patch
# Copy printed ID into CANDIDATE. No ref was moved.
arcen harness --store "$STORE" budget create --trials 2 --model-calls 8 --judge-calls 1 --seconds 600
# Copy printed ID into BUDGET. Deadline starts at creation, not at run.
arcen harness --store "$STORE" campaign plan --baseline "$BASELINE" --candidate "$CANDIDATE" --task-file ./task.txt --commit "$(git rev-parse HEAD)" --budget "$BUDGET"
# Copy printed ID into CAMPAIGN.
arcen harness --store "$STORE" campaign run "$CAMPAIGN" --task-file ./task.txt --config ./arcen.yaml --repo . --budget "$BUDGET"
```

Specify up to five distinct candidates by repeating `--candidate`. One baseline
trial is shared across candidates. The run requires an interactive terminal and
prints the commit, repository, bound budget ID, usage and limits, provider host,
task and sanitized diffs, then requires exactly `RUN CAMPAIGN_ID`. It does **not**
show the full endpoint, config or repository tree: verify those separately.
The budget display is a snapshot, not a reservation; cooperating processes may
consume admissions or stop it at any time. The admission cutoff is not a runtime
limit. Confirming is not authenticated identity
or proof of understanding; terminal sanitization is not byte-for-byte review.
No provider or Docker activity is initiated before confirmation. The CLI refuses
legacy plans that do not bind a budget; create a new plan instead. The Python
API still permits explicitly unbound plans for compatibility.

After successful trials, inspect the untrusted, reduced A/B evidence and choose
`A`, `B`, `TIE` or `CANCEL`. Labels are randomized but blinding can leak
provenance. Evidence and tasks may contain sensitive data; filtering is best
effort. The CLI stores a nominal confidence of 0.5 and the fixed reason
“manual preference; confidence not assessed”—this is not a calibrated score.
`CANCEL` stops with no review for that comparison. Previously created pending
reviews remain. Inspect records with `arcen harness --store "$STORE" review
list` and `review show REVIEW_ID`. Review decisions are unsigned, do not adopt,
and are not a safety authorization. The displayed candidate or baseline might
not be the active adopted ref.

Admission limits count cooperating trial/model/judge attempts only; they are
**not USD/token caps, runtime cancellation or a limit on other processes**.
Stop commands only act at stage boundaries and do not interrupt in-flight work.
A crashed run is ambiguous, can leave containers or partial review records, and
must not be automatically resumed. Inspect the journal, pending reviews and
Docker state before deciding what to do. The journal stores task hashes, not
secrets-proof encryption. The local filesystem, Docker daemon and image remain
trusted. See `HARNESS-MANUAL-CAMPAIGN.md`, `HARNESS-CAMPAIGN-JOURNAL.md`,
`HARNESS-DURABLE-BUDGET.md` and `HARNESS-REVIEW.md` for details.

The automated CLI tests use a mocked provider and mocked Docker. An opt-in
real-Docker test exists but was not run in the assistant sandbox. It is separate
from the user's earlier verified Docker tests of the underlying campaign API.
