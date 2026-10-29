# Probe preflight (execution unavailable)

H-09 currently provides **preflight only**. `prepare_probe` reads and verifies
stored baseline and candidate manifests, requires the same explicit fixed model
pin, checks that the supplied configuration matches it, locks guardrails and
registry metadata to the currently packaged baseline, and resolves the candidate
prompt files into an immutable snapshot. Only the existing editable prompt and
guidance paths may differ. It neither launches a task nor contacts a model.

`run_probe` deliberately raises `ProbeUnavailable`: a selected-harness executor,
identical isolated workspaces, empty credential envelope, forced redaction,
container teardown and `spawn` event integration have **not** been completed.
There is no process-backend or host fallback. The current workspace snapshot
mechanism can include secret files explicitly present in the chosen directory;
its existing behavior must not be advertised as an empty-credential guarantee.
Prompt validation and preflight are not approval or proof that edited prompts
are safe. H-09 is incomplete, and no probe or recursive campaign can run yet.

The caller supplies configuration and owns the store; fixed model names are not
cryptographic identities for model weights. A malicious local process with
write access to the package or store is outside this integrity mechanism's
trust boundary. See `HARNESS-EDITOR.md` and `HARNESS-STORE.md` for other limits.
