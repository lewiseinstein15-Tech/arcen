# TUI adapter recordings

Both JSONL files are fresh, isolated recordings of the real `server.app.run_turn`
pipeline, stored through its `StreamEmitter` and validated against the frozen
event schema. They use a temporary HOME and session directory; timestamps are
set to zero and IDs/goals are deterministic. No user session data or credentials
are included.

- `server-replan.jsonl`: a deterministic mock planner first requests `exit 3`,
  then `echo fixed` and `true`; the real tool registry executes those harmless
  commands. Captures command failure, replan, recovery, verification and answer.
- `server-offline.jsonl`: no provider, legitimate build goal; records the real
  honest configure-a-provider response without pretending tools ran.

The replan recording is also packaged under `arcen/tui/fixtures/` for the
explicitly offline `arcen-tui --demo --replay` visual demonstration. A test
asserts that the packaged copy matches this recording exactly.
