## plan
Return ONLY a JSON array of 1-6 steps for this goal, shaped:
[{"title": "imperative step", "tool": "bash|file.read|file.edit|file.list|file.glob|search.text", "args": {}}]
"args" carries the tool's arguments and is REQUIRED on every step:
- bash → {"cmd": "the exact shell command"}
- file.read → {"path": "file", "offset_line": 0, "limit_lines": 2000}
- file.edit → {"path": "file", "find": "exact text", "replace": "new text"} (optional "count")
- file.list → {"path": "."}
- file.glob → {"pattern": "**/*.py"}
- search.text → {"pattern": "python regex", "root": ".", "glob": "*.py"}
The isolated turn runs as an unprivileged user inside /workspace with no network.
Prefer bash for anything the listed tools do not cover.
No prose, no markdown fences.
## research
Return ONLY a JSON array of 1-4 steps to RESEARCH this goal, shaped:
[{"title": "imperative step", "tool": "file.read|file.list|file.glob|search.text", "args": {}}]
The isolated turn has no network access: read and search files in /workspace.
Prefer search.text for locating code, then file.read for specific files.
Every step carries its args. No prose, no markdown fences.
