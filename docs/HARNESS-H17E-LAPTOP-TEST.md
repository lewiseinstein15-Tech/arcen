# H-17e durable parallel probes: laptop Docker test

This opt-in smoke test runs one reference and two candidates using three real,
disposable Docker containers, a mocked model provider, and a local SQLite
durable budget and slot cap. It holds both candidate containers open at once,
then asks a **separate local Python process** to acquire a third slot and checks
that it is refused without consuming a trial. It verifies common snapshot,
network-disabled Docker boundary, host marker absence, container cleanup,
unchanged host workspace, zero remaining occupied slots, and no adoption.
The 19 durable-slot tests separately include a killed local subprocess; that
crash test does not run a Docker container. There is no live provider or judge.

## Run from the previous H-12d laptop checkout

Requires the earlier `~/arcen-h12d-test` checkout (containing commit `2ff50ba`),
`uv`, a working trusted Docker daemon, and sufficient memory to build the image
and run two containers concurrently. Download `000-000-h17e-docker-test.bundle`
to `~/Downloads/`. These commands create a new detached worktree and `.venv`;
choose another worktree name if `~/arcen-h17e-test` already exists. The old
checkout's files are not changed; the shared Git repository gains fetched
objects and worktree metadata. The image/build cache and new worktree remain.

```sh
(
set -e
git -C ~/arcen-h12d-test fetch ~/Downloads/000-000-h17e-docker-test.bundle HEAD
git -C ~/arcen-h12d-test worktree add --detach ~/arcen-h17e-test FETCH_HEAD
cd ~/arcen-h17e-test
git rev-parse HEAD
uv venv --python 3.12
uv pip install --python .venv/bin/python '.[dev,tui]'
docker info >/dev/null
docker build -t arcen-h12-test:local docker/sandbox
ARCEN_TEST_DOCKER_ISOLATION=1 ARCEN_H12_DOCKER_IMAGE=arcen-h12-test:local \
  .venv/bin/python -m pytest -o addopts='' -q -rs \
  tests/test_h17e_docker.py tests/test_durable_trial_slots.py
)
```

Expected: **21 passed, no skips**. One test uses the real Docker boundary; one
uses a mocked Docker boundary, and 19 test SQLite/slots with mocked or no Docker.
If the opt-in flag is set, missing Docker or its SDK fails rather than skips.
The fake marker is not a credential, and no paid-provider call is made.

Please share the `git rev-parse` output and the pytest summary; if a failure
occurs, include the traceback after checking it for private information. Do not
paste credentials. If interrupted, inspect `docker ps -a --filter label=arcen.turn`;
do not remove unrelated containers. Passing this smoke test is not a full
security certification, safe crash recovery, universal concurrency enforcement,
a live-provider validation, or completion of H-14/H-17.

## User-reported laptop result

The user reported running the commands above at commit
`51d971a32240dafb26c7a478c7fda5371652c74d` with Python 3.12.14 and image
`arcen-h12-test:local`. The image built successfully, and pytest reported
**21 passed in 55.69s**, with no skips. This is the user's terminal report, not
an independent execution in the agent workspace. One test used three real
Docker containers, including two concurrently held candidates; the other
process checked the SQLite slot limit. Model responses were mocked; no judge or
paid provider was used. This narrow smoke does not validate live-provider
behavior, container crash recovery, universal concurrency enforcement, safe
resume, adoption, or the complete H-14/H-17 tickets.
