# Manual campaign progress and validation

Manual CLI campaigns can display live, metadata-only progress after the existing
interactive confirmation. Events describe static review, reference and candidate
probes, the local human comparison, pending-review creation and the final result.
No task text, prompt, transcript, provider error, path or credential is included
in these progress dictionaries. IDs and outcomes can themselves be sensitive.

The trusted Python API accepts an optional `on_progress` callback. Events are
in-process and separately sequenced per invocation; observer exceptions are
ignored, events may be lost, and unexpected errors can end a run without a
terminal event. They are not durable, signed or authoritative, and cannot resume
or approve a campaign. Callbacks are trusted local code and can themselves
perform side effects or raise `BaseException`. The interactive human judge's
0.5 confidence field is a placeholder, not an assessed confidence. A passed static review, successful probe or positive
judgment is not proof of safety or permission to adopt. The legacy 17-event wire
contract is unchanged; these progress events are not yet integrated into the
session NDJSON stream or Harness TUI.

`.github/workflows/harness-validation.yml` defines installed-wheel test jobs on
Python 3.12 and 3.13 and a separate real-Docker job that builds the local sandbox
image. Live-provider requests are not part of CI; campaign provider and judge
fixtures in these tests are mocked. The workflow has read-only repository
permissions and does not persist checkout credentials. It is a CI configuration,
not evidence that a remote run passed; inspect GitHub Actions after it is pushed.
A hosted-runner result does not replace validation on the operator's deployment.
