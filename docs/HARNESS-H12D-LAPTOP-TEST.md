# H-12d workspace-bound plan: laptop Docker test

This opt-in test covers the schema-v3 recorded workspace guard using the H-12c
and H-12d smoke suites. Prior campaigns use fabricated data and mocked Docker.
For H-12d, the test creates a composite plan, cancels at `RUN`, checks that its
unsigned workspace hash remains in the plan, then makes a **separate manual CLI
invocation**. In the success case, that invocation starts two real, disposable
Docker containers and verifies execution and cleanup. In a separate mismatch
case, the test injects a different snapshot hash and confirms no new containers,
model calls or trial admissions. It does not resume an interrupted running
campaign. H-12c tests repeat the direct composite flow against this revision.

All provider responses, operator confirmations and A/B judgment are mocked; no
paid provider is contacted. These tests are not a security certification,
authenticated provenance, adoption authorization, or proof of safe resume.
Older plans do not gain a hash binding during migration.

## Run using the previous laptop checkout

Requires the earlier `~/arcen-h12c-test` Git checkout and `uv`, and a trusted,
working local Docker daemon. Download `000-arcen-h12d-docker-test.bundle` to
`~/Downloads/`. These commands create a *new* worktree; choose another name if
`~/arcen-h12d-test` already exists. The old checkout's files are not changed,
although the shared Git repository gains the fetched objects/worktree metadata.
Docker image/build caches and the new worktree remain after testing.

```sh
git -C ~/arcen-h12c-test fetch ~/Downloads/000-arcen-h12d-docker-test.bundle HEAD
git -C ~/arcen-h12c-test worktree add --detach ~/arcen-h12d-test FETCH_HEAD
cd ~/arcen-h12d-test
git rev-parse HEAD
uv venv --python 3.12
uv pip install --python .venv/bin/python '.[dev,tui]'
docker info >/dev/null
docker build -t arcen-h12-test:local docker/sandbox
ARCEN_TEST_DOCKER_ISOLATION=1 ARCEN_H12_DOCKER_IMAGE=arcen-h12-test:local \
  .venv/bin/python -m pytest -o addopts='' -q -rs \
  tests/test_h12d_docker.py tests/test_h12c_docker.py
```

Expected **8 passed, no skips**: four mocked-boundary cases and four opt-in
Docker cases. The two mismatch cases check Docker daemon and image access but
intentionally create no containers. The two success cases create two distinct
containers apiece, execute and verify scripted workspace commands, and check
container removal. The marker checked inside containers is fabricated, not an
actual credential. If Docker or its SDK is unavailable with the opt-in flag,
the tests fail rather than silently skip. `docker build` success alone is not a
pytest pass.

Share the commit and pytest summary, and any traceback after checking for
private information. Do not paste credentials. If a test is interrupted,
inspect `docker ps -a --filter label=arcen.turn` and do not automatically remove
unrelated containers. The bundle requires base commit
`779853b3cc7a81abf64190ff531c1e8961103462` in the previous checkout.
