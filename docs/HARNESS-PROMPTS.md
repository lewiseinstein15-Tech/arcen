# File-based prompts

H-02 stores the default prompts in the installed package under
`arcen/prompts/{system,draft,forge,temper}.md`. The source files live under
`src/arcen/prompts/`. The default resolver reads the four UTF-8 files into one
immutable process snapshot together with `arcen/tool-guidance.md`; restart ARCEN after modifying them. No network or
model call is needed for resolution.

`system.md` is the shared identity template and must use exactly `{agent}` and
`{job}`. The other files have `## section-name` headings. DRAFT has `job`,
`classify`, `strict`, `direct`, `goal-template`, and `failed-step-template`
sections; `tool-guidance.md` has `plan` and `research`; FORGE and TEMPER each
have `job`. The goal and
failed-step templates must use `{goal}` and `{step}`, respectively. Each
section must be nonempty. Files must use LF line endings and end in a newline;
the resolver removes only the single separator newline from each section, so
prompt content is otherwise passed through unchanged.

Missing files, unreadable files, invalid UTF-8, duplicate or missing sections,
invalid template fields, and files over 128 KiB raise `HarnessError`. The
resolver does not fall back to hard-coded prompts. An explicit trusted harness
root may be resolved with `HarnessResolver(root).resolve()`; it must contain a
`prompts/` directory with all four files and `tool-guidance.md` at the root. Prompt directory and file symlinks are
rejected. Callers can pass the resulting immutable snapshot to `Client`; its
`DraftPlanner` inherits that snapshot. This API is for trusted local inputs,
not a policy sandbox for untrusted edits.

Harness refs, an adoption store, manifests, and the `--harness` CLI option were
**not implemented by H-03**. Later work permits selecting only the verified
packaged baseline; candidates remain blocked rather than silently ignored. See [HARNESS-GUARDRAILS.md](HARNESS-GUARDRAILS.md)
for guardrail validation and the important distinction between preserved tool
guidance and tools currently supported by the isolated gateway. Editable-harness
governance arrives in later tickets.

For compatibility, `tests/fixtures/prompts/H-02-before.json` records the actual
model-message payloads from before externalization using a deterministic mocked
provider. The golden test compares all 12 captured payloads, including direct,
research, plan, strict retry, replan, executor, and verifier messages.

The shipped `harness.toml` additionally verifies component hashes at server
startup. See [HARNESS-MANIFEST.md](HARNESS-MANIFEST.md) for update requirements
and the important limits of unsigned hashes and the default unpinned model.
