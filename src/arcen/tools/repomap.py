"""ARCEN — repo.map (Part 3 wrapped).

A very large repository does not fit in a context window, and reading files
alphabetically is the worst possible order: it opens vendored code and
changelogs before the module that owns the bug. ``repo.map`` returns a ranked
skeleton instead — path, line count, symbol count, and the first few symbol
names — so the planner can spend its reads where the code actually is.

Ranking is deliberately crude and explainable: symbols dominate, size
contributes up to a fixed cap. Vendored and generated directories are skipped
by the same list the isolated helper uses.
"""

from __future__ import annotations

import fnmatch
import os
import re

from pydantic import BaseModel, Field

from .registry import BaseTool

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
TEXT_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".rb",
    ".php",
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".hpp",
    ".cs",
    ".kt",
    ".swift",
    ".scala",
    ".sh",
    ".sql",
    ".vue",
    ".svelte",
    ".md",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
}
MAX_FILE_BYTES = 1_000_000
SYMBOL_RE = re.compile(
    r"^\s*(?:async\s+)?(?:def|class|function|func|fn|interface|struct|enum|type|impl|module)\s+([A-Za-z_]\w*)"
    r"|^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_]\w*)\s*=",
    re.MULTILINE,
)


def build_map(root: str, *, max_files: int = 60, include: str = "*") -> dict:
    scanned = 0
    files: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for fname in sorted(filenames):
            if not fnmatch.fnmatch(fname, include):
                continue
            full = os.path.join(dirpath, fname)
            if os.path.splitext(fname)[1].lower() not in TEXT_SUFFIXES:
                continue
            try:
                if os.path.getsize(full) > MAX_FILE_BYTES:
                    continue
                with open(full, "r", encoding="utf-8", errors="ignore") as fh:
                    text = fh.read()
            except OSError:
                continue
            scanned += 1
            symbols = [m.group(1) or m.group(2) for m in SYMBOL_RE.finditer(text)]
            lines = text.count("\n") + 1
            files.append(
                {
                    "path": os.path.relpath(full, root),
                    "lines": lines,
                    "symbols": len(symbols),
                    "top": symbols[:8],
                    "rank": len(symbols) * 3 + min(lines // 20, 20),
                }
            )
    files.sort(key=lambda f: (-f["rank"], f["path"]))
    return {
        "files": files[:max_files],
        "scanned": scanned,
        "truncated": len(files) > max_files,
        "root": os.path.relpath(root, os.getcwd()) if os.path.isabs(root) else root,
    }


class RepoMap(BaseTool):
    name = "repo.map"
    description = (
        "Ranked skeleton of a tree (path, lines, symbol count, top symbols) for large codebases."
    )
    danger = "safe"

    class Args(BaseModel):
        root: str = Field(default=".", description="directory to map")
        max_files: int = Field(default=60, ge=1, le=400, description="how many files to return")
        include: str = Field(default="*", description="filename glob to include")

    def _run(self, a: Args) -> dict:
        if not os.path.isdir(a.root):
            raise ValueError("root is not a directory")
        return build_map(a.root, max_files=a.max_files, include=a.include)
