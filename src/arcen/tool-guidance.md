## plan
Return ONLY a JSON array of 1-6 steps for this goal, shaped:
[{"title": "imperative step", "tool": "bash|file.read|file.edit|file.write|search.text|...", "args": {}}]
"args" carries the tool's arguments and is REQUIRED on every step:
- bash → {"cmd": "the exact shell command"}
- file.read / file.write / file.edit → {"path": "..."} (file.write adds "content")
- search.text → {"query": "..."};  http.get → {"url": "..."}
- only tools that truly take no arguments (e.g. file.list) get {}
No prose, no markdown fences.
## research
Return ONLY a JSON array of 1-4 steps to RESEARCH this goal, shaped:
[{"title": "imperative step", "tool": "search.text|http.get|http.post|file.read|file.write", "args": {}}]
Prefer search.text ({"query": "..."}) for queries and http.get ({"url": "..."})
for specific URLs. Every step carries its args. No prose, no markdown fences.
