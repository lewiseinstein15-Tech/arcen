# Headless runs

`arcen run` drives the same DRAFT → FORGE → TEMPER turn as the server, without
starting a server or requiring a TTY:

```bash
arcen run "explain Python closures" --json
arcen run "inspect the files" --json --workspace ./project
```

JSON stdout is one versioned [result envelope](headless-result.schema.json)
containing the canonical event sequence, answer, status, error, run ID and
session ID. `workspace_mode: snapshot_requested` records the request, not proof
that an import succeeded. Diagnostics go to stderr. Exit code 0 means success; 1 means a
failed, refused, interrupted or errored turn; argparse usage errors return 2.
The runner persists the normal session log under the configured session path.

The safety policy is the same as the server: Docker is required for tools,
network is disabled, and no process fallback is permitted. Only `bash` is
currently available. A run that needs unavailable isolation emits
`SANDBOX_UNAVAILABLE` and exits nonzero. A non-tool conversational answer
can succeed without Docker. A missing provider or unusable plan is a failed
headless task even though the legacy interactive event stream marks its
refusal as `run.done: ok`.

## Workspace snapshots

`--workspace` copies a directory into `/workspace` in the per-turn container;
it is **not a host bind mount**. It is input-only: changes made inside the
container are discarded, not applied to the source directory. The entire
selected directory is included, including hidden files and possible secrets;
select only data you are willing to expose in tool output and to the model
provider. Symbolic links and special files are rejected rather than followed;
the snapshot is limited to 10,000 entries and 64 MiB of file content. The
read-only container root is retained: a non-root importer receives the snapshot
through Docker exec stdin and writes only into the container's workspace tmpfs.
The snapshot is not an atomic filesystem snapshot: don't change the source while
it is being read. The container is destroyed after the turn.

## Selecting the packaged baseline

`arcen harness init` initializes a private local store with the packaged
baseline. Headless runs can explicitly select only that verified baseline:

```bash
arcen harness init
arcen run "hello" --json --harness adopted
# An alternative trusted store can be supplied explicitly:
arcen run "hello" --json --harness refs/heads/adopted --harness-store /path/to/store
```

The runner verifies the ref, all stored object hashes and equality with the
currently packaged manifest before a turn. It uses the same packaged prompt
snapshot as an ordinary run and records the immutable manifest identity as
`sha256:<digest>` in `run.start.harness_ref`. With no `--harness`, legacy event
bytes remain unchanged. The store is trusted local state; hashes do not attest
author or prevent a hostile local user from modifying code or the package.

**Candidate refs are still rejected.** This baseline-only path does not enable
candidate execution, approval, adoption, probe campaigns or rollback. A missing,
corrupt or non-packaged adopted ref fails rather than falling back. The default
manifest's `provider-configured` model pin does not freeze a model's identity.

The real Docker integration checks are opt-in:

```bash
ARCEN_TEST_DOCKER_ISOLATION=1 pytest tests/test_turn_isolation.py tests/test_headless.py -k real_docker -v
```

They require the Docker SDK extra, a reachable trusted Docker daemon, and the
configured local sandbox image. Passing mock-based tests does not establish real
container isolation or prove workspace import works on a particular daemon.
