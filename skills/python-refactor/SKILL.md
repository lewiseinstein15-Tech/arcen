---
name: python-refactor
version: 0.1.0
description: Refactor Python safely - move code without changing behaviour
tools: [bash, file.read, file.edit, search.text, search.symbols, git.status, git.diff]
---

# Safe Python refactor

Behaviour must be provably unchanged. Tests are the proof; run them before
you start so you know the baseline.

1. Establish the baseline: `bash {"cmd": "python -m pytest -q"}`. Record the
   count. A refactor that changes the count is a bug report.
2. Map the blast radius: `search.symbols {"pattern": "OldName"}` and
   `search.text {"pattern": "OldName\\b"}`. Both, because strings and imports
   are not symbols.
3. Refactor in one direction per step: rename, then move, then inline. Never
   two at once — a failure must have one candidate cause.
4. Keep public names stable unless the task says otherwise. If you must
   rename, do it with a single `search.replace` scoped by glob, then read the
   diff.
5. Run the tests after every step, not at the end.
6. Read `git.diff` before declaring done. Every changed line should be a line
   you intended to change.
7. If a test had to change, justify it explicitly: which behaviour changed and
   why the old assertion was wrong.
