# Probe preflight and experimental reviewed trial

H-09 provides preflight plus a limited, explicitly reviewed experimental trial.
`prepare_probe` reads and verifies
stored baseline and candidate manifests, requires the same explicit fixed model
pin, checks that the supplied configuration matches it, locks guardrails and
registry metadata to the currently packaged baseline, and resolves the candidate
prompt files into an immutable snapshot. Only the existing editable prompt and
guidance paths may differ. It neither launches a task nor contacts a model.

The original `run_probe` deliberately raises `ProbeUnavailable`: the complete
campaign executor, guaranteed credential-free inputs, end-to-end secret
protection, and `spawn` event integration have **not** been completed. A
separate limited `run_reviewed_probe` API is described below.
There is no process-backend or host fallback. The current workspace snapshot
mechanism can include secret files explicitly present in the chosen directory;
its existing behavior must not be advertised as an empty-credential guarantee.
Prompt validation and preflight are not approval or proof that edited prompts
are safe. H-09 remains incomplete, and no recursive campaign can run yet.

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
Review every input before exposing it to a model/provider. The standard
`run_probe` is not wired to these APIs; the experimental trial below combines
the gateway and model. There is no automatic adoption or campaign runtime. The local unit tests mock Docker;
the opt-in real-Docker test must be run on a machine with the sandbox image.

## Bound candidate model calls (not a complete probe)

`bind_probe_model(store, baseline_id, candidate_id, task, config)` reruns the
preflight against verified stored objects, requires a matching explicit fixed
provider/model pin, resolves a private configuration snapshot, and binds the
candidate's immutable prompt snapshot to the existing LiteLLM bridge. Binding
itself does not contact the provider. Explicit `complete` calls **do** send
messages to the configured provider and can incur cost; make a deliberate
privacy decision and review all inputs first. The returned client can be used by the existing DRAFT planner. The experimental
reviewed trial below combines it with the Docker gateway; the standard
`run_probe` remains blocked.

The binding rejects detected secret patterns and the resolved provider key in
prompt and message inputs, redacts those patterns from model output, suppresses
provider error text, disables retries and enforces a thread-safe per-client cap
of 1–8 calls. Each request asks the provider for at most 1,024 output tokens and
a 30-second timeout; enforcement of those two request parameters depends on the
provider/SDK. Inputs and returned output are size-limited. This is not a USD,
token, total wall-clock or campaign budget, and the response may already have
been buffered by a provider SDK before its output-size check.

Filtering is best effort: encoded, split, previously unknown, short or other
secrets can evade it. A checked model name does not authenticate model weights;
model output is untrusted. The object-store and local Python caller are trusted;
this API is not a security boundary against an arbitrary local process. Do not
send confidential tasks, prompts or repository data unless sharing them with the
configured provider is acceptable. No real provider was called in unit tests.
The standard `run_probe` remains blocked pending the complete campaign safety
gates; this binding alone does not constitute a successful probe.

## Experimental manually reviewed trial

The trusted Python API `run_reviewed_probe` in `arcen.harness.probe_execution`
combines the candidate model binding, an explicit full Git commit snapshot, and
one fresh Docker-only gateway. The caller must explicitly pass
`reviewed_inputs=True` after reviewing the task, candidate prompts, commit and
provider exposure; this flag is an attestation, **not** a verified human
approval workflow. The container is opened before model calls, has no host bind
mount or network, and is subject to the existing Docker policy. It is strictly
removed before a result is returned; cleanup failure raises an error rather than
returning success, though a daemon failure may leave a container for manual
inspection. There is no host or process fallback.

The trial collects an in-memory, recursively redacted event trajectory and
supports at most four plan steps, bash only, a 30-second command limit, and the
bounded model-call interface described above. It stops at the first tool failure;
there is no replan or subagent spawning. For a successful tool plan, TEMPER
**reruns the last command once** inside the same disposable container to check
it. That can repeat side effects inside the container; workspace changes are not
copied back. A direct answer is also run with a container opened and closed.

This is not the ordinary shared server turn or the complete H-09 campaign
prober. The standard `run_probe` remains unavailable, there is no CLI, no
persisted trajectory, approval, ref movement or adoption. An explicitly
reviewed paired-comparison API is described in `HARNESS-COMPARISON.md`.
Inputs and outputs can contain secrets that filtering does not recognize;
review does not prove otherwise. The model provider may receive task and prompt
content and can incur cost. The sandbox image, Docker daemon, Git repository,
package and local Python caller must be trusted. The assistant environment has
no Docker. The user reported the opt-in real-Docker test passed on Omarchy at
`f34ea27` with a mocked model provider (see `docs/verify/README.md`).
