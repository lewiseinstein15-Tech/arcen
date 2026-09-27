"""ARCEN — file tools (BACKEND-SPEC Part 2, row 6 — OpenHands tools/ pattern).

read / write / edit / append / delete / copy / move / list / glob / mkdir —
ten tools, each wrapped in the frozen Tool schema (Part 3).
``file.edit`` replaces an exact string (the Aider / OpenHands minimal-diff
pattern); it fails as a value when the needle is not found or is ambiguous.
"""

from __future__ import annotations

import glob as globmod
import os
import shutil

from pydantic import BaseModel, Field

from .registry import BaseTool, _err, _ok

MAX_BYTES = 2_000_000  # refuse to slurp huge files


class _PathArgs(BaseModel):
    path: str = Field(description="file path")


class _SrcDstArgs(BaseModel):
    src: str = Field(description="source path")
    dst: str = Field(description="destination path")


class FileRead(BaseTool):
    name = "file.read"
    description = "Read a UTF-8 text file. Returns the content and its size."
    version = "1.0.0"
    danger = "safe"

    class Args(_PathArgs):
        offset_line: int = Field(default=0, ge=0, description="start at this line (0-based)")
        limit_lines: int = Field(default=2000, ge=1, description="max lines returned")

    def _run(self, a: "FileRead.Args") -> dict:
        with open(a.path, "rb") as fh:
            raw = fh.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError(f"file larger than {MAX_BYTES} bytes; read a slice instead")
        lines = raw.decode("utf-8", errors="replace").splitlines()
        picked = lines[a.offset_line : a.offset_line + a.limit_lines]
        return {
            "path": a.path,
            "total_lines": len(lines),
            "content": "\n".join(picked),
            "truncated": len(lines) > a.offset_line + a.limit_lines,
        }


class FileWrite(BaseTool):
    name = "file.write"
    description = "Write content to a file, creating parent directories. Overwrites."
    version = "1.0.0"
    danger = "sandboxed"

    class Args(_PathArgs):
        content: str = Field(description="full file content")

    def _run(self, a: "FileWrite.Args") -> dict:
        os.makedirs(os.path.dirname(a.path) or ".", exist_ok=True)
        with open(a.path, "w", encoding="utf-8") as fh:
            fh.write(a.content)
        return {"path": a.path, "bytes": len(a.content.encode("utf-8"))}


class FileEdit(BaseTool):
    name = "file.edit"
    description = "Replace an exact string in a file. Fails if the needle is missing or ambiguous."
    version = "1.0.0"
    danger = "sandboxed"

    class Args(_PathArgs):
        find: str = Field(description="exact text to replace")
        replace: str = Field(description="replacement text")
        count: int = Field(default=-1, description="max replacements (-1 = all)")

    def _run(self, a: "FileEdit.Args") -> dict:
        with open(a.path, "r", encoding="utf-8") as fh:
            content = fh.read()
        occurrences = content.count(a.find)
        if occurrences == 0:
            raise ValueError(f"needle not found in {a.path}")
        if a.count >= 0 and occurrences > a.count:
            raise ValueError(f"needle is ambiguous: {occurrences} occurrences, count={a.count}")
        updated = content.replace(a.find, a.replace) if a.count < 0 else content.replace(a.find, a.replace, a.count)
        with open(a.path, "w", encoding="utf-8") as fh:
            fh.write(updated)
        return {
            "path": a.path,
            "bytes_changed": len(updated.encode("utf-8")) - len(content.encode("utf-8")),
            "replacements": occurrences if a.count < 0 else min(a.count, occurrences),
        }


class FileAppend(BaseTool):
    name = "file.append"
    description = "Append content to the end of a file."
    version = "1.0.0"
    danger = "sandboxed"

    class Args(_PathArgs):
        content: str = Field(description="text to append")

    def _run(self, a: "FileAppend.Args") -> dict:
        with open(a.path, "a", encoding="utf-8") as fh:
            fh.write(a.content)
        return {"path": a.path, "bytes": len(a.content.encode("utf-8"))}


class FileDelete(BaseTool):
    name = "file.delete"
    description = "Delete a file. Destructive — requires escalation in sandboxed runs."
    version = "1.0.0"
    danger = "escalate"

    class Args(_PathArgs):
        pass

    def _run(self, a: "FileDelete.Args") -> dict:
        os.remove(a.path)
        return {"path": a.path, "deleted": True}


class FileCopy(BaseTool):
    name = "file.copy"
    description = "Copy a file to another path."
    version = "1.0.0"
    danger = "sandboxed"

    class Args(_SrcDstArgs):
        pass

    def _run(self, a: "FileCopy.Args") -> dict:
        os.makedirs(os.path.dirname(a.dst) or ".", exist_ok=True)
        shutil.copy2(a.src, a.dst)
        return {"src": a.src, "dst": a.dst}


class FileMove(BaseTool):
    name = "file.move"
    description = "Move or rename a file."
    version = "1.0.0"
    danger = "sandboxed"

    class Args(_SrcDstArgs):
        pass

    def _run(self, a: "FileMove.Args") -> dict:
        os.makedirs(os.path.dirname(a.dst) or ".", exist_ok=True)
        shutil.move(a.src, a.dst)
        return {"src": a.src, "dst": a.dst}


class FileList(BaseTool):
    name = "file.list"
    description = "List a directory's entries with type and size."
    version = "1.0.0"
    danger = "safe"

    class Args(_PathArgs):
        pass

    def _run(self, a: "FileList.Args") -> dict:
        entries = []
        for name in sorted(os.listdir(a.path)):
            full = os.path.join(a.path, name)
            entries.append(
                {
                    "name": name,
                    "type": "dir" if os.path.isdir(full) else "file",
                    "size": os.path.getsize(full) if os.path.isfile(full) else None,
                }
            )
        return {"path": a.path, "entries": entries}


class FileGlob(BaseTool):
    name = "file.glob"
    description = "Expand a glob pattern to matching paths, sorted."
    version = "1.0.0"
    danger = "safe"

    class Args(BaseModel):
        pattern: str = Field(description="glob pattern, e.g. src/**/*.py")
        limit: int = Field(default=500, ge=1, description="max matches")

    def _run(self, a: "FileGlob.Args") -> dict:
        matches = sorted(globmod.glob(a.pattern, recursive=True))[: a.limit]
        return {"pattern": a.pattern, "matches": matches, "count": len(matches)}


class FileMkdir(BaseTool):
    name = "file.mkdir"
    description = "Create a directory and any missing parents."
    version = "1.0.0"
    danger = "sandboxed"

    class Args(_PathArgs):
        pass

    def _run(self, a: "FileMkdir.Args") -> dict:
        os.makedirs(a.path, exist_ok=True)
        return {"path": a.path, "created": True}
