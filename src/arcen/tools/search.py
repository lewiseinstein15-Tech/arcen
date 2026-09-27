"""ARCEN — search tools (OpenHands tools/ pattern, wrapped in Part 3).

text search across files, file lookup, Python symbol search, bulk replace.
"""

from __future__ import annotations

import os
import re

from pydantic import BaseModel, Field

from .registry import BaseTool

MAX_FILE_BYTES = 2_000_000
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}


class SearchText(BaseTool):
    name = "search.text"
    description = "Regex search across text files under a root. Returns path, line number, and line."
    version = "1.0.0"
    danger = "safe"

    class Args(BaseModel):
        pattern: str = Field(description="Python regex")
        root: str = Field(default=".", description="directory to walk")
        glob: str = Field(default="*", description="filename filter, e.g. *.py")
        limit: int = Field(default=200, ge=1, description="max matches")

    def _run(self, a: "SearchText.Args") -> dict:
        rx = re.compile(a.pattern)
        matches: list[dict] = []
        for dirpath, dirnames, filenames in os.walk(a.root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fname in filenames:
                if not re.fullmatch(a.glob.replace("*", ".*").replace("?", "."), fname):
                    continue
                full = os.path.join(dirpath, fname)
                try:
                    with open(full, "r", encoding="utf-8", errors="ignore") as fh:
                        for lineno, line in enumerate(fh, 1):
                            if rx.search(line):
                                matches.append({"path": full, "line": lineno, "text": line.rstrip()[:300]})
                                if len(matches) >= a.limit:
                                    return {"matches": matches, "count": len(matches), "truncated": True}
                except OSError:
                    continue
        return {"matches": matches, "count": len(matches), "truncated": False}


class SearchFiles(BaseTool):
    name = "search.files"
    description = "Find files under a root whose name matches a pattern."
    version = "1.0.0"
    danger = "safe"

    class Args(BaseModel):
        pattern: str = Field(description="regex against the file name")
        root: str = Field(default=".", description="directory to walk")
        limit: int = Field(default=500, ge=1, description="max matches")

    def _run(self, a: "SearchFiles.Args") -> dict:
        rx = re.compile(a.pattern)
        found: list[str] = []
        for dirpath, dirnames, filenames in os.walk(a.root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fname in filenames:
                if rx.search(fname):
                    found.append(os.path.join(dirpath, fname))
                    if len(found) >= a.limit:
                        return {"files": found, "count": len(found), "truncated": True}
        return {"files": found, "count": len(found), "truncated": False}


class SearchSymbols(BaseTool):
    name = "search.symbols"
    description = "List top-level Python definitions (def/class/async def) in a file or tree."
    version = "1.0.0"
    danger = "safe"

    class Args(BaseModel):
        path: str = Field(description=".py file or directory")
        limit: int = Field(default=500, ge=1, description="max symbols")

    def _run(self, a: "SearchSymbols.Args") -> dict:
        rx = re.compile(r"^(async\s+def|def|class)\s+([A-Za-z_]\w*)")
        symbols: list[dict] = []
        if os.path.isfile(a.path):
            targets = [a.path]
        elif os.path.isdir(a.path):
            targets = []
            for dirpath, dirnames, filenames in os.walk(a.path):
                dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
                targets.extend(os.path.join(dirpath, f) for f in filenames if f.endswith(".py"))
        else:
            targets = []
        for target in targets:
            try:
                with open(target, "r", encoding="utf-8", errors="ignore") as fh:
                    for lineno, line in enumerate(fh, 1):
                        m = rx.match(line)
                        if m and not line.startswith((" ", "\t")):
                            symbols.append({"path": target, "line": lineno, "kind": m.group(1), "name": m.group(2)})
                            if len(symbols) >= a.limit:
                                return {"symbols": symbols, "count": len(symbols), "truncated": True}
            except OSError:
                continue
        return {"symbols": symbols, "count": len(symbols), "truncated": False}


class SearchReplace(BaseTool):
    name = "search.replace"
    description = "Regex replace across every text file under a root. Reports per-file counts."
    version = "1.0.0"
    danger = "sandboxed"

    class Args(BaseModel):
        pattern: str = Field(description="Python regex")
        replace: str = Field(description="replacement (may use \\1 groups)")
        root: str = Field(default=".", description="directory to walk")
        glob: str = Field(default="*", description="filename filter, e.g. *.py")
        dry_run: bool = Field(default=True, description="report counts without writing")

    def _run(self, a: "SearchReplace.Args") -> dict:
        rx = re.compile(a.pattern)
        changed: list[dict] = []
        for dirpath, dirnames, filenames in os.walk(a.root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fname in filenames:
                if not re.fullmatch(a.glob.replace("*", ".*").replace("?", "."), fname):
                    continue
                full = os.path.join(dirpath, fname)
                try:
                    with open(full, "r", encoding="utf-8", errors="ignore") as fh:
                        content = fh.read(MAX_FILE_BYTES)
                    new, n = rx.subn(a.replace, content)
                    if n:
                        changed.append({"path": full, "replacements": n})
                        if not a.dry_run:
                            with open(full, "w", encoding="utf-8") as fh:
                                fh.write(new)
                except OSError:
                    continue
        return {"changed": changed, "files": len(changed), "dry_run": a.dry_run}
