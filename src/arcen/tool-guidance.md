## plan
Return ONLY a JSON array of 1-6 steps for this goal, shaped:
[{"title": "imperative step", "tool": "<name from the catalog>", "args": {}}]
"args" carries the tool's arguments and is REQUIRED on every step, matching
the argument list the catalog prints for that tool. A step naming a tool that
is not in the catalog is dropped, so never invent a name.
The isolated turn runs as an unprivileged user inside /workspace with no
network. bash is available for anything the catalog does not cover — and for
git, which works offline against the workspace repository.
Prefer the narrowest tool that does the job: a targeted file.edit over a bash
one-liner, search.text over a recursive grep.
No prose, no markdown fences.
## research
Return ONLY a JSON array of 1-4 steps to RESEARCH this goal, shaped:
[{"title": "imperative step", "tool": "<name from the catalog>", "args": {}}]
The isolated turn has no network access: read and search files in /workspace.
Prefer search.text and repo.map for locating code, then file.read for
specific files.
Every step carries its args. No prose, no markdown fences.
