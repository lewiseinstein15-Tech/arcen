"""ARCEN — patch.apply (Part 3 wrapped).

A unified diff is the cheapest way for a model to make a multi-file change
without rewriting whole files, and ``git apply`` is the safest way to land
one: it is atomic per file, refuses fuzz, and never runs a shell. ``check``
lets TEMPER verify a patch applies before anyone commits to it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .git import _git
from .registry import BaseTool

MAX_PATCH_BYTES = 400_000


class PatchApply(BaseTool):
    name = "patch.apply"
    description = "Apply a unified diff (git apply) to the workspace; check=true only validates."
    danger = "sandboxed"

    class Args(BaseModel):
        patch: str = Field(min_length=1, description="unified diff text")
        root: str = Field(default=".", description="working tree to apply against")
        reverse: bool = Field(default=False, description="apply the patch backwards")
        check: bool = Field(default=False, description="validate without writing")

    def _run(self, a: Args) -> dict:
        if len(a.patch.encode("utf-8")) > MAX_PATCH_BYTES:
            raise ValueError(f"patch larger than {MAX_PATCH_BYTES} bytes")
        argv = ["apply", "--whitespace=nowarn"]
        if a.reverse:
            argv.append("--reverse")
        if a.check:
            argv.append("--check")
        _git(a.root, argv + ["-"], stdin=a.patch)
        files = sorted(
            {
                line.split("+++ b/")[-1].strip()
                for line in a.patch.splitlines()
                if line.startswith("+++ b/")
            }
        )
        return {"applied": not a.check, "check_only": a.check, "files": files}
