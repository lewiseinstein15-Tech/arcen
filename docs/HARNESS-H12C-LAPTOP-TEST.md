# H-12c composite continuation: laptop Docker test

This opt-in smoke test exercises the new `campaign compose` → separate `PLAN`
→ `RUN` → human-style A/B choice workflow. The recorded input campaign is a
fabricated fixture created with mocked Docker and provider calls. For the new
composite test, two fresh **real Docker containers** run the scripted command;
the test checks their separate identities, successful command and verification,
removal, unchanged host repository, budget usage, pending review and no adoption.
It also injects a snapshot hash mismatch and checks that it stops before any
container, model call or trial admission. The operator's confirmations and
judgment and all model calls are mocked; this is not a paid-provider test or a
security certification. The real-Docker mismatch case checks the daemon/image
but deliberately creates no containers.

## Prerequisites

Linux with Git, `uv`, Docker CLI and a running daemon accessible to your current
user. Trust the daemon and sandbox image. Internet is needed for dependencies,
clone and image build. The tests create disposable containers, a temporary Git
repository and a separate local image tag. Build caches and this checkout remain.

Download `000-arcen-h12c-docker-test.bundle` into `~/Downloads/`. Choose a
new directory name if `~/arcen-h12c-test` already exists. In your terminal:

```sh
cd ~
git clone https://github.com/lewiseinstein15-Tech/arcen.git arcen-h12c-test
cd arcen-h12c-test
git fetch ~/Downloads/000-arcen-h12c-docker-test.bundle HEAD
git switch --detach FETCH_HEAD
git rev-parse HEAD
uv venv --python 3.12
uv pip install --python .venv/bin/python '.[dev,tui]'
docker info >/dev/null
docker build -t arcen-h12-test:local docker/sandbox
ARCEN_TEST_DOCKER_ISOLATION=1 ARCEN_H12_DOCKER_IMAGE=arcen-h12-test:local \
  .venv/bin/python -m pytest -o addopts='' -q -rs tests/test_h12c_docker.py
```

The bundle needs base commit `779853b3cc7a81abf64190ff531c1e8961103462`,
which must exist in the GitHub clone. Expected: **4 passed**, with no skips: two
mock-boundary cases and two opt-in real-Docker cases (a successful pair and an
injected snapshot mismatch). A Docker/image/SDK problem must fail, not skip,
when the environment variable is set. Share the printed full commit, pytest
summary and any failure traceback after checking them for private information;
never paste credentials. `docker info` and building the image test daemon access,
but a successful image build alone does not mean the pytest cases passed.

The test does not push or modify your original checkout. Container operations
can be interrupted; if cleanup cannot be confirmed, inspect containers labelled
`arcen.turn` with `docker ps -a --filter label=arcen.turn`. Do not automatically
remove unrelated containers. This smoke does not prove full H-12, authenticated
provenance or isolation against every attack. A workspace hash is unsigned and
is not saved in the created plan; a later ordinary run lacks this guard.

## User-reported laptop result

On 31 October 2026 the user reported running the instructions above at commit
`db75d86d6d67f3b0dd4e2396a9e366bdd45d1968`, using Python 3.12.14 and
`arcen-h12-test:local`. The Docker image built successfully and pytest reported
**4 passed in 38.29s** with no skips. The user-provided terminal output is the
source for this result; it was not independently run in the agent workspace.
The two real-Docker cases exercised a successful composite test and a simulated
snapshot mismatch (the latter deliberately starts no containers). Prior recorded
campaigns, model responses, confirmations and human-style judgment were mocked.
The pass does not establish provider integration, authentication, safe resume,
full isolation against every attack, or completion of H-12.
