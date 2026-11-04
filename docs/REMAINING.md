# Remaining work

## Current state and limitations

This is the **partial salvage branch**, reconstructed from `796659e`; it is
not the missing original branch through `cbd7fe4`. The earlier complete history
and evidence bundle are unavailable. See `RECOVERY-STATUS.md`. Do not treat
passing tests as proof that all lost work was recovered or that this build is
ready for production.

The latest complete salvage regression, at `359e8fc`, was **1,837 backend
passed, 19 skipped**, and **87 UI tests passed**. In the recovery workspace the
logs are `~/phase-evidence/A-03a-continuation/backend-api-smoke.log` and
`ui-api-smoke.log`; they are not automatically included in a Git checkout.
Those results predate the documentation-only handoff and its merge. Real Docker
and live-provider verification were not run in the salvage environment.

## Next: A-03b patch application

- Exercise `arcen apply SESSION` through the CLI after a fake turn and export:
  default dry run, changed-file listing, `--yes` application, and a passing
  deterministic test command against the controlled fixture.
- Verify failure on a different HEAD and overlapping uncommitted changes; test
  the explicitly authorized `--allow-different-base` option separately. Do not
  commit, push, or modify the user's working tree as part of `apply`.
- Exercise malicious paths, secrets, size limits, binary/new/deleted files,
  and executable-mode restrictions through the integrated pipeline. Existing
  helper and fake-runtime tests are not a real Docker proof.
- Perform the Docker-machine procedure in `A03-SMOKE.md` and save command output
  and exit codes. Mark A-03 **Done (mock) - needs Docker run** only when its
  mock acceptance criteria are met; do not report Docker success before a real
  run. Review the known non-atomic check/apply race with concurrent writers.

## Remaining phases

- **A-01:** validate TEMPER against real sandbox test discovery and execution;
  no-test runs must remain explicitly unverified.
- **A-02 / BENCH-1:** implement the complete benchmark/adapters and run real
  isolated tasks, including the required 20-task bank, scripts and patch
  scoring. Current fixtures and scorer are fake-tested only; no resolution,
  cost, or task-time metrics have been measured.
- **A-08:** validate live-provider token/cost reporting; unknown values remain
  unmeasured and must not be counted as measured zero.
- **A-06, A-07, A-10–A-14:** complete their remaining work and acceptance gates.
  In particular, the A-10 semantic exception-handler review is incomplete;
  syntax-only proposals are not semantic findings. A-11 has socket mocks, not
  proof of real cleanup; A-12 and A-14 still have UI work/warnings; A-13 must
  resolve provenance and license verification before copying external code.
- Complete the broader phases 2–9 and final evidence gates in the original
  order where the surviving plan permits. The original master prompt is not in
  this recovery workspace; do not invent its missing requirements.

## Safety and compatibility notes

- Headless `--workspace` exports through a host baseline and host-generated
  diff. HTTP `/api/run` intentionally rejects workspace paths; it is not a
  remote host-file selection interface. Session reuse for a workspace baseline
  is refused. Review workspace contents: filename checks cannot detect secrets
  embedded in arbitrary files.
- Preserve the frozen 17 event types, sandbox network and no-host-bind limits,
  Git-filter refusal, and host-side treatment of container output as untrusted.
  Never run candidate code on the host to construct or validate a patch.
- Use focused tests for each small step, then the complete backend and UI suites
  once at the end of each slice, save textual evidence, commit each step, and
  add the progress line specified in `PROGRESS.md`.
