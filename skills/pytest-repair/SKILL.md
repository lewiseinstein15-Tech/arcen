---
name: pytest-repair
version: 0.1.0
description: Fix failing pytest suites with minimal diffs
tools: [bash, file.read, file.edit]
---

# Pytest Repair

1. Run `pytest -q` and capture the first failure.
2. Read the failing test and the module under test.
3. Decide: test bug or code bug.
4. Apply the minimal edit.
5. Re-run the suite. Pass → report. Fail → escalate to DRAFT.
