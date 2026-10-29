# Bundled harness manifest

`arcen/harness.toml` contains schema version 1, a model-pin declaration and
SHA-256 hashes for the seven packaged components currently implemented: the four
prompt files, tool guidance, the guardrail policy and tool-registry metadata.
ARCEN validates the allowlisted paths and file hashes at server startup. Missing,
malformed, unexpected or changed files stop startup. The manifest is included
in the wheel. The resolved manifest is immutable in memory.

These hashes detect changes relative to the manifest; **they are not digital
signatures**. An attacker who can alter both the manifest and component files
can replace the hashes. This mechanism does not make a hostile package safe.
Ref resolution, an authenticated trust root, signed manifests, and adoption
remain future work. The component list does not yet represent all eight planned
Harness² components.

The shipped model pin is `provider-configured`, which intentionally leaves the
user's existing model selection unchanged. It is **not a fixed model pin**.
Trusted packages may use `fixed:<provider>:<model>` instead; boot and config
updates reject a provider, default model or agent/subagent override that doesn't
match. This matches configured model names, not the provider's actual model
weights or a cryptographic model identity. Campaign-level frozen model snapshots
and ref selection are not implemented. Avoid editing an installed package;
for trusted source edits, update the SHA-256 manifest entries alongside changed
component files and restart.

The `harnessing.enabled` configuration field defaults to `false` and cannot be
set true yet; no editor, campaign, or autonomous adoption is enabled by this
manifest. The Docker-only guardrails remain independent hard requirements.
