# Offline Harness² TUI demo

```sh
arcen-tui --demo --harness
```

This is a **simulation**: it plays fabricated metadata through a read-only
progress renderer in the real TUI shell. It does not start a server, campaign,
model, Docker container or judge; it does not read or modify a harness store,
open a review, authorize a candidate or change any ref. IDs, verdicts and
confidence in the demo are fictional. The header and goal identify it as
simulated; progress cards describe the pending review and lack of adoption.

The renderer accepts the existing in-process manual campaign progress schema,
rejects malformed, duplicated and unexpected-field events, and shows only
metadata. It is **not connected** to the live server stream or to a running
manual campaign. Progress is best-effort, can be lost and is locally forgeable;
it is not an authenticated log or evidence that an action happened. Confidence
is uncalibrated. There is no approval UI, persistent replay or safe resume.

Use the existing manual harness CLI to perform real, explicitly reviewed work;
its confirmation and safety requirements still apply. H-20 and H-22 remain open.
The ordinary `arcen-tui --demo`, `--demo --replay`, and live TUI behavior are
unchanged.
