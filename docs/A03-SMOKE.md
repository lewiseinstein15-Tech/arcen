# A-03 Docker-machine smoke — not yet run for this salvage branch

This exercise uses a disposable Git fixture and a deterministic local fake
planner. It requires a working Docker daemon, the Docker Python SDK, Git and
a locally installed ARCEN development environment. It does not use a paid
provider, run untrusted candidate code on the host, push, or commit to a real
project. Run only after reviewing the checkout and its dependencies.

In an isolated virtual environment at the repository root:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev,tui]'
git --no-lazy-fetch --version
docker version
docker info
docker build -t ghcr.io/lewiseinstein15-tech/arcen-sandbox:0.1.0 docker/sandbox
ARCEN_TEST_DOCKER_ISOLATION=1 python -m pytest -o asyncio_default_fixture_loop_scope=function -o addopts='' -q tests/test_headless.py::test_real_docker_headless_workspace_when_enabled
```

The Git preflight must succeed: older Git versions without `--no-lazy-fetch`
are refused by the protected baseline path. Save the command output, version
information, checkout commit, and exit code
as text evidence. Do not include API keys or private configuration. The test
creates a temporary Git root and private temporary HOME, uses the same isolated
container for editing and discovery, checks no-test verification is honestly
`unverified`, and checks the host is unchanged until a dry-run and explicit
apply. Its final fixed local assertion reads only that controlled test fixture.
A passing result verifies this smoke test only; it is not a provider test,
network-isolation audit, or broad benchmark. The build can use network access;
the actual turn must retain Docker `network_mode=none` and no host bind mounts.

The HTTP API refuses workspace paths; this smoke exercises the local headless
path. A filename denylist cannot detect secrets embedded in arbitrary files:
review real workspaces before invoking ARCEN. Docker has not been available in
the salvage environment, so no Docker pass is claimed here.
