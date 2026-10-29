# File-based prompts

H-02 stores the default prompts in the installed package under
`arcen/prompts/{system,draft,forge,temper}.md`. The source files live under
`src/arcen/prompts/`. The default resolver reads the four UTF-8 files into one
immutable process snapshot; restart ARCEN after modifying them. No network or
model call is needed for resolution.

`system.md` is the shared identity template and must use exactly `{agent}` and
`{job}`. The other files have `## section-name` headings. DRAFT has `job`,
`classify`, `plan`, `research`, `strict`, `direct`, `goal-template`, and
`failed-step-template` sections; FORGE and TEMPER each have `job`. The goal and
failed-step templates must use `{goal}` and `{step}`, respectively. Each
section must be nonempty. Files must use LF line endings and end in a newline;
the resolver removes only the single separator newline from each section, so
prompt content is otherwise passed through unchanged.

Missing files, unreadable files, invalid UTF-8, duplicate or missing sections,
invalid template fields, and files over 128 KiB raise `HarnessError`. The
resolver does not fall back to hard-coded prompts. An explicit trusted harness
root may be resolved with `HarnessResolver(root).resolve()`; it must contain a
`prompts/` directory with all four files. Prompt directory and file symlinks are
rejected. Callers can pass the resulting immutable snapshot to `Client`; its
`DraftPlanner` inherits that snapshot. This API is for trusted local inputs,
not a policy sandbox for untrusted edits.

Harness refs, an adoption store, manifests, and the `--harness` CLI option are
**not implemented by H-02**. The CLI continues to reject requested refs rather
than pretending to use them. Guardrail policy and editable-harness governance
arrive in later tickets.

For compatibility, `tests/fixtures/prompts/H-02-before.json` records the actual
model-message payloads from before externalization using a deterministic mocked
provider. The golden test compares all 12 captured payloads, including direct,
research, plan, strict retry, replan, executor, and verifier messages.
