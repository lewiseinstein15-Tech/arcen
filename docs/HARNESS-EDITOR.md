# Offline editor proposal foundation

H-08 adds `arcen.harness.editor.propose`: a trusted caller supplies a verified
stored manifest, a task, one or more model callbacks and `k` (1–5). For each
invariant and domain scope, the API asks for one JSON-encoded, single-file
unified diff per candidate. Every candidate starts from the same baseline. It
returns immutable proposal records and makes no store writes, tool calls,
execution, or adoption decisions itself.

Only the four existing prompt files and `tool-guidance.md` are editable here.
Guardrails, registry metadata, plugins, sandbox settings, and all other paths
are rejected. Diffs have exact path headers, exact line context and offsets,
bounded size, and are applied in memory without a shell. The resulting complete
prompt set must pass the existing resolver validation. A malicious callback can
still propose bad prompt content within the allowed paths; validation is not an
approval, safety judgment, proof of task improvement, or prompt-injection
filter. Candidate bytes and user-supplied task text should be treated as
untrusted.

## Interactive model-backed proposals

`arcen harness editor propose` exposes a limited, explicitly confirmed path
through the existing LiteLLM binding. It uses the **same fixed provider/model
pin as the baseline**, not a separate editor model or model panel. It sends the
task and all five editable baseline components to that provider. First inspect
the exact task, packaged baseline components, config, provider and endpoint;
network requests can disclose information and cost money. The command does not
inspect the full endpoint for you, and secret detection is best effort. Manual
commands use the stricter configuration parser described in
`HARNESS-MANUAL-CLI.md`.

```sh
arcen harness --store "$STORE" editor propose --baseline "$BASELINE" \
  --task-file ./task.txt --config ./arcen.yaml --budget "$BUDGET" --k 1
```

It requires interactive stdin/stdout and exact `EDIT BASELINE_ID` confirmation.
`k` is 1–4. It requests `k` invariant and `k` domain proposals, independently
from the same unchanged packaged baseline, charging up to `2*k` model call
admissions. An attempt is consumed even if it fails. The output limit and
provider timeout are best effort and depend on provider/SDK behavior. A budget
is not a USD/token cap; an in-flight call is not cancelled by stop. A model may
return duplicate proposals or invalid output, and no automatic retry occurs.

All model responses are untrusted. Each candidate must pass strict patch,
prompt and protected-core validation, then is saved as an **unadopted** object
and displayed as a sanitized diff. No ref is moved. Some immutable objects may
remain if persistence or display fails; inspect outputs before retrying.
Sanitization does not make a candidate safe or prove task improvement. Review
and select distinct candidates manually for the separate interactive campaign;
no tests run automatically and nothing is selected, approved or adopted.
`--harness` still rejects candidate refs. There is no model panel, recursive
editor, automatic campaign orchestration, authenticated approval or autonomy.

The CLI tests use a local HTTP mock provider and mocked provider calls, not a
real external provider; the assistant environment did not verify paid-provider
compatibility.
