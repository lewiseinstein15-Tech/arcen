# Opt-in campaign progress stream bridge (H-11i, partial)

Seven existing manual campaign progress messages have a strict metadata-only
wire representation: `harness.campaign.start`, `harness.policy`,
`harness.probe.start`, `harness.probe.done`, `harness.judge`, `harness.review`,
and `harness.campaign.done`. Their content is limited to IDs, enumerated
statuses, counts and confidence. They contain no task text, transcript, patch,
provider output or credentials. Best-effort validation does not authenticate
local records and cannot make an untrusted process or subscriber safe.

A trusted Python caller can pass `ProgressStream(emitter)` as the existing
manual campaign `on_progress` callback. The emitter stamps a timestamp and
shares one session sequence with legacy events. It remains in-memory; subscribers
and records may be modified or lost. Ordinary observer errors are ignored by
manual progress, so events must never be treated as a completion guarantee.
The bridge does not contact providers or Docker by itself and does not start
or control a campaign.

`from_v2_dict`, `from_v2_line` and `to_v2_line` validate this narrow contract,
reject extra fields, duplicate JSON keys and invalid timestamps; they are not
interchangeable with the frozen legacy decoder. Legacy `EVENT_TYPES` remains
unchanged: the strict legacy Python decoder rejects unknown v2 types, while the
legacy TUI adapter ignores unknown types and consumes their sequence numbers.
An application can explicitly call `register_v2_progress(adapter)` to render the
validated messages as unsigned, advisory cards. `arcen-tui --harness-progress`
opts the live client into the same reader; default behavior remains unchanged.
The offline `arcen-tui --demo --harness` simulation uses that bridge; it is
fabricated and runs no campaign.

This is not the full event contract in the architecture: proposal, composition,
canary, budget, approval and adoption events are not implemented here. ARCEN's
live server and campaign CLI do not produce these events; the opt-in client can
only render them if a compatible producer sends them. There is no persistent event
log, evidence authentication, completion proof, safe replay/resume or adoption.
The policy and judge labels describe local observations, not approval or a
safety decision. Real campaign execution and model behavior are not established
by the simulated demo or mocked integration tests.
