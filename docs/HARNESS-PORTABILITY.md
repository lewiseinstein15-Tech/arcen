# Manual two-image portability comparisons (experimental)

This is an **advisory experiment**, not a portability certification, safety
proof, approval or adoption gate. Review and trust the local Docker daemon, both
image contents, the exact Git commit, task, candidate diff, config and provider
endpoint before running it. It uses Docker-only, network-disabled containers;
there is no host-execution fallback. Image IDs do not prove safe contents, a
separate kernel/architecture, independent environments or trustworthy results.

Obtain **local image IDs** only after inspecting them independently. Two
canonical, distinct IDs of the form `sha256:<64 lowercase hex>` are required;
tags are not accepted. The CLI does not pull images or inspect their safety, and
a missing second image can fail after the first comparison already incurred
costs. The CI smoke test creates a labelled variant of the same image: this is
not meaningful evidence of real-world environment diversity.

```sh
arcen harness --store "$STORE" portability run \
  --baseline "$BASELINE" --candidate "$CANDIDATE" \
  --task-file ./task.txt --config ./arcen.yaml \
  --repo . --commit "$FULL_COMMIT" --budget "$BUDGET" \
  --image-a "$LOCAL_IMAGE_ID_A" --image-b "$LOCAL_IMAGE_ID_B"
```

The command requires a terminal, an unchanged packaged baseline pinned to the
provider, a separate candidate, an explicit confirmation, and two blinded human
A/B judgments. It displays the task and sanitized diff but does not show every
piece of data that may reach the provider; read the full inputs/config outside
the CLI too. Judge evidence is untrusted and may contain secrets. A result marked
`compared` means both callbacks returned valid judgments, **not** that tests
passed or that the candidate is better. Judgments use the existing placeholder
confidence of 0.5, not a calibrated score.

The two profiles use the same task, provider configuration and Git commit. Each
profile re-archives the commit once; the second archive must match the first
archive's SHA-256 before its first trial. This hash is an equality check, not
an authenticated binding to the repository. Four fresh containers/trials and
up to 16 model calls share one durable admission budget. The displayed minimum
is not a reservation; other processes can spend it, and a stop or exhaustion
can interrupt between profiles. Neither trial nor callback is cancelled in
flight, and no token, USD or hard-runtime cap is enforced. Failed or uncertain
runs can consume admissions and incur charges. Inspect usage and external side
effects; there is no automatic resume.

For Python callers, `arcen.harness.portability.run_portability_comparison`
requires `reviewed_inputs=True`, `reviewed_judge_inputs=True` and
`reviewed_images=True` plus a shared budget. It can accept explicitly supplied
`sensitive_values` using the existing exact-known-value checks. Attestations,
reports, callbacks and image IDs are local and unsigned. Neither API nor CLI
records a review, checks current active-baseline freshness for authorization,
moves refs, chooses a winner for adoption or enables autonomous action.

The new two-image path is mock-tested locally. An opt-in real-Docker test can
use two trusted local image IDs in `ARCEN_PORTABILITY_IMAGE_A` and
`ARCEN_PORTABILITY_IMAGE_B`, with `ARCEN_TEST_DOCKER_ISOLATION=1`; the provider
and judge in that test are mocked. The corresponding CI configuration has not
yet run remotely. Real Docker, independent environment profiles, an executor
adapter contract, authenticated evidence, live-provider validation and the full
H-21 acceptance criteria remain outstanding.
