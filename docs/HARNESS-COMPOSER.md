# Offline harness composer (H-12 foundation)

`compose_proposals(store, baseline_id, proposals)` combines one to ten editor
`Proposal` objects that each apply independently to the same verified baseline.
It rechecks each exact diff, source hash and result, verifies the packaged
protected policy and registry, validates the complete prompt set, and preserves
the baseline model pin. Proposals can change only the editor's prompt/guidance
allowlist.

Distinct, non-touching base-line edits can be merged within a file, while
identical edits are deduplicated. Overlapping or touching edits—including
competing insertions at the same boundary—are conservatively returned as
`Conflict(path, first, second)` records with zero-based proposal indices. On
conflict it returns no candidate ID and writes no objects. In the guided manual
workflow, an operator can choose generated proposals for composition, inspect
the resulting diff, and separately confirm a comparison. The workflow reports
conflicts and stops; it does not resolve them. A no-conflict result creates
immutable content-addressed blobs and a successor manifest; it never changes a
ref or records a lineage decision. A storage failure can leave unreferenced blobs.

This is a **syntactic** merge, not an assessment of prompt compatibility,
correctness, safety or improvement. Candidates are unapproved. The standalone
composer does not run a model, probe, judge, canary or approval. The separate
reviewed proposal-comparison API can compose and then run experimental paired
trials; candidate runtime selection and adoption still fail closed. Guided
composition happens before comparison of its inputs and is not evidence-based.
H-12 remains incomplete until behavioral-contrast selection, iterative campaign
integration and a reviewed conflict-resolution workflow are implemented.

A separate interactive `campaign compose` command can reconstruct and combine
operator-selected candidates from one completed campaign's locally recorded
comparison summaries. The local summaries are unsigned, full trajectories
are not retained, and the newly combined candidate must be tested separately.
See `HARNESS-RECORDED-COMPOSITION.md`; this is not automatic behavioral
selection, authenticated evidence or adoption.

## Python-only conflict handoff (experimental)

`preview_proposals(store, baseline_id, proposals)` validates and analyzes the
exact proposals without writing blobs or a manifest. For conflicts,
`draft_conflict_resolutions(store, baseline_id, proposals, editor,
reviewed_callback_inputs=True)` sends one request per conflicting path to a
caller-provided callback. It returns an **unpersisted draft**, not a candidate,
approval, or decision; the caller must inspect every replacement and then
separately choose whether to call `compose_proposals` and test the result.

The callback sees the entire baseline component and all supplied proposal
diffs for that path, as well as zero-based conflicting indices. It may transmit
data, call a model and incur cost; this module does not provide provider
isolation, authentication, secret redaction, billing limits or runtime caps.
Review all content and trust the callback before explicitly opting in. The
response must be JSON with exactly `path` and `diff`: one non-empty exact
base-relative unified diff for the same editable path. Invalid or unsafe
responses and callback failures are rejected; callback errors are sanitized.

A replacement **supersedes every proposal for that path**, including edits
that were not themselves in conflict. The callback may discard or alter any
such edit, and a structurally valid patch is not necessarily safe, useful or
faithful to the inputs. Other paths' proposals are retained. Recheck the full
diff manually; there is no automatic approval, adoption, probing, persistence,
network restriction for the callback, or durable audit. Concurrent hostile
local writers and side effects performed by the callback are outside this
module's guarantees. Multiple callback calls may occur before a later failure.
The guided editor workflow still aborts on conflicts. The separate recorded
campaign CLI supports manually supplied local replacement patches as described
in `HARNESS-RECORDED-COMPOSITION.md`; it does not call a model or run a probe.
