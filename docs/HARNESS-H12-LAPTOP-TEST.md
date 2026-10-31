# H-12 composed-candidate Docker smoke test

This opt-in test composes two compatible edits, compares the composite with its
baseline in two fresh local Docker containers, checks both use the same Git
snapshot, and confirms the containers are removed. It checks that a marker from
the test runner's environment is absent inside the container and that the host
repository is unchanged. The provider and judge are **mocked**: there is no
external model call, paid-provider validation, authenticated evidence or
automatic adoption. A pass does not prove full H-12 recursion or safety.

## Prerequisites

Linux with Docker CLI, a running Docker daemon accessible to your current user,
Git and `uv`; Internet access is needed to install packages and build the image.
The Docker daemon and sandbox image must be trusted. The test builds a separate
local image tag and creates/removes disposable containers. Docker/build caches
and the test checkout remain on disk.

Download `000-arcen-h12-docker-test.bundle` to `~/Downloads/`, then run in your
own terminal. The new `arcen-h12-test` directory must not already exist:

```sh
cd ~
git clone https://github.com/lewiseinstein15-Tech/arcen.git arcen-h12-test
cd arcen-h12-test
git fetch ~/Downloads/000-arcen-h12-docker-test.bundle HEAD
git switch --detach FETCH_HEAD
git rev-parse --short HEAD
uv venv --python 3.12
uv pip install --python .venv/bin/python '.[dev,tui]'
docker info >/dev/null
docker build -t arcen-h12-test:local docker/sandbox
ARCEN_TEST_DOCKER_ISOLATION=1 ARCEN_H12_DOCKER_IMAGE=arcen-h12-test:local \
  .venv/bin/python -m pytest -q -rs tests/test_h12_docker.py
```

The bundle requires Git commit `779853b3cc7a81abf64190ff531c1e8961103462`,
which must be present in the clone. The expected result is **2 passed**: one
mocked-boundary test and one real-Docker test. If Docker is unavailable or the
SDK is missing when opted in, the real test fails rather than silently skipping.
Share the commit printed by `git rev-parse`, the pytest summary and any failure
traceback, after checking it for private information. Do not paste credentials.

The test does not modify your original ARCEN checkout or push anything. It uses
only fabricated prompt edits, a temporary test repository, and mocked model and
judge responses. An interrupted daemon/container operation can still require
manual inspection of Docker resources; do not assume cleanup after a crash.
