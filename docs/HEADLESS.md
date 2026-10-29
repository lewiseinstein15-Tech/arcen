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

`--harness` is parsed but **currently rejected**. The store and inspection CLI now exist, but runtime ref selection and its
safety gates are not implemented; silently ignoring a requested ref would be
unsafe. Use the default behavior without `--harness` until then.

The real Docker integration checks are opt-in:

```bash
ARCEN_TEST_DOCKER_ISOLATION=1 pytest tests/test_turn_isolation.py tests/test_headless.py -k real_docker -v
```

They require the Docker SDK extra, a reachable trusted Docker daemon, and the
configured local sandbox image. Passing mock-based tests does not establish real
container isolation or prove workspace import works on a particular daemon.
