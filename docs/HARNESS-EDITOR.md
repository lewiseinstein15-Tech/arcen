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

The callback interface is not yet wired to LiteLLM or to a CLI/campaign. Model
budgets, isolated probes, judging, full tier policy, human approval and all
adoption remain unimplemented. The API alone does not test or apply proposals;
`--harness` still rejects refs. Real provider calls, quarantined execution and
end-to-end recursive improvement must not be claimed until those gates exist.
