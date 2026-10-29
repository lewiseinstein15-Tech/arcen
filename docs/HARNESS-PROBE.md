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

## Git input and container foundations (still not a probe runner)

`snapshot_git_commit(repo, commit)` accepts an explicit full local commit ID,
not a branch or an arbitrary command. It runs fixed Git commands with a minimal
host environment and produces a bounded, normalized archive. Untracked files,
working-tree changes and `.git` are excluded; Git archive attributes such as
`export-ignore` still apply. Links, submodules and special files are rejected,
as are common credential filenames and directories. Archive content and limits
are checked again on temporary materialization, which is removed on exit.
The commit ID and archive hash are **not an authenticated binding**: construct
snapshots in trusted code from the reviewed repository and commit rather than
accepting a caller-supplied `GitSnapshot` as proof of origin.

`open_probe_container(snapshot, config)` imports that temporary tree into the
existing Docker-only turn boundary and closes it on exit, including exceptions.
No workspace is bind-mounted or copied back. Results pass through mandatory
best-effort redaction of known secret patterns and the configured provider key;
unsupported nested result values are suppressed. The sandbox image and Docker
daemon are trusted. Tool support is limited to the existing bash gateway.

**Neither filename blocking nor output redaction proves an input secret-free.**
Committed source, task text, prompts, encoded/split values, errors outside the
wrapped tool-result path, and other data may still contain or reveal secrets.
Review every input before exposing it to a model/provider. These APIs are not
wired to `run_probe`, model calls, trajectory storage, spawn events, approval,
or adoption; the runtime still fails closed. The local unit tests mock Docker;
the opt-in real-Docker test must be run on a machine with the sandbox image.
