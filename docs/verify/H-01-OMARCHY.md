# H-01 — user-reported Omarchy Docker verification

The user ran the opt-in integration tests on their Omarchy machine and supplied
terminal output in the conversation. These are user-reported results, not
screenshots captured by the workspace harness.

- Sandbox safety branch `a42baa3`: `ARCEN_TEST_DOCKER_ISOLATION=1 python -m
  pytest tests/test_turn_isolation.py -k real_docker -v` — **1 passed, 15
  deselected** in 3.54 seconds. This exercised the host-file/environment and
  network checks in the real Docker test.
- H-01 branch `d6f805d`: `ARCEN_TEST_DOCKER_ISOLATION=1 python -m pytest
  tests/test_headless.py -k real_docker -v` — **1 passed, 8 deselected** in
  8.32 seconds. This exercised a workspace snapshot, a mocked planner, the
  headless FORGE/TEMPER execution path and preservation of the host input.
  The output reported Linux, Python 3.13.15 and pytest 9.2.0.

The first H-01 live attempt on `8655110` failed because Docker refused
`put_archive` for a read-only rootfs. The subsequent result above is after
`d6f805d`, which imports through an unprivileged exec stdin instead.

These tests are targeted checks, not a proof against every container escape or
all deployment configurations. Harness references remain unimplemented and
are explicitly rejected rather than silently ignored.
