---
name: debug-traceback
version: 0.1.0
description: Root-cause a traceback or failing command instead of guessing at fixes
tools: [bash, file.read, search.text, file.edit]
---

# Debug a traceback

Guessing is the failure mode this skill exists to prevent. Reproduce, read,
then fix.

1. Reproduce with the smallest command that still fails. Quote it exactly:
   `bash {"cmd": "python -m pytest tests/test_x.py::test_y -x -q"}`.
2. Read the *bottom* of the traceback first: the exception type and message
   name the failure; the frames above it name the path.
3. Open the exact file and line from the last frame of user code (not the
   library frame below it) with `file.read` and a line window.
4. State the cause in one sentence before editing: "X is None because Y
   returned early". If you cannot state it, go back to step 1.
5. Search for every other call site of the function you are about to change
   (`search.text {"pattern": "func_name\\("}`) — a fix that breaks a caller is
   not a fix.
6. Make the smallest edit that removes the cause. Do not reformat, rename, or
   "clean up" while debugging.
7. Re-run the exact command from step 1, then the wider suite.
8. If the fix was a workaround, say so and name the real cause you did not fix.
