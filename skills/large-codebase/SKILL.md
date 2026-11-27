---
name: large-codebase
version: 0.1.0
description: Navigate a very large repository without burning the context window
tools: [repo.map, search.text, search.symbols, file.read, file.glob, bash]
---

# Navigate a large codebase

Reading files in alphabetical order is how agents waste a context window.
Rank first, then read narrow.

1. `repo.map {"max_files": 60}` — the ranked skeleton. Files with many
   symbols and many lines are where the logic lives.
2. Find the entry point before the implementation: `search.text {"pattern":
   "def main|if __name__|app = FastAPI|func main"}`, or the CLI/pyproject
   config that names the real module.
3. Find the definition, not the mention: `search.symbols {"pattern": "Name"}`
   separates `def Name` from `Name(...)`.
4. Read with a window: `file.read {"path": "x.py", "offset_line": 120,
   "limit_lines": 80}`. Read the whole file only when it is under ~300 lines.
5. Follow one call chain at a time, and write down the chain as you go. If you
   lose the thread, `repo.map` is cheaper than re-reading.
6. Vendored, generated, and build directories are noise: skip `node_modules`,
   `dist`, `build`, `vendor`, `.venv`, `__pycache__`.
7. Before editing, confirm the file you are about to change is the one the
   runtime loads — not a stale copy, a shim, or a re-export.
