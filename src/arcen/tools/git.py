"""ARCEN — git tools (Part 3 wrapped).

The sandbox image ships git, but until now the only way to reach it was a
raw ``bash`` string: the planner had no schema, no structured result, and no
guard against a step that quietly ran ``git push``. These tools give the
model a narrow, typed surface over the operations real work needs — inspect,
stage, commit, branch — and nothing else.

Two implementations back the same contract. Inside a turn the isolated
helper (``arcen.sandbox.isolated_ops``) runs the command in the container;
these classes run it on the host, which is what the CLI does. The argv shapes
are deliberately identical, and ``tests/test_git_tools.py`` asserts both
produce the same result for the same repository so they cannot drift.

Every operation is offline: fetch, pull, push and remote configuration are
absent by construction, not by policy.
"""

from __future__ import annotations

import os
import re
import subprocess

from pydantic import BaseModel, Field

from .registry import BaseTool

OUTPUT_LIMIT = 60_000
TIMEOUT_S = 60
_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_ASKPASS": "/bin/true",
    "GIT_PAGER": "cat",
    "PAGER": "cat",
}
_BASE = [
    "git",
    "-c",
    "safe.directory=*",
    "-c",
    "user.name=ARCEN",
    "-c",
    "user.email=arcen@localhost",
]


_REF = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._/@{}^~:-]{0,200}\Z")


def _path(p: str) -> str:
    """Repo-relative, no traversal, no option-looking name."""
    if not p or p.startswith(("/", "-")) or ".." in p.split("/") or "\x00" in p:
        raise ValueError(f"invalid repository path: {p!r}")
    return p


def _ref(ref: str) -> str:
    if not _REF.match(ref) or ".." in ref:
        raise ValueError(f"invalid git ref: {ref!r}")
    return ref


def _git(root: str, argv: list[str], stdin: str | None = None) -> str:
    env = dict(os.environ)
    env.update(_ENV)
    proc = subprocess.run(
        _BASE + ["-C", root] + argv,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_S,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise RuntimeError(detail[-1][:500] if detail else "git failed")
    return proc.stdout


def _status(root: str) -> dict:
    out = _git(root, ["status", "--porcelain=v1", "--branch"])
    branch, ahead, behind = "", 0, 0
    staged: list[dict] = []
    unstaged: list[dict] = []
    untracked: list[str] = []
    for line in out.splitlines():
        if line.startswith("## "):
            head = line[3:]
            branch = head.split("...")[0].split(" ")[0]
            for token in head.split():
                if token.startswith("ahead "):
                    ahead = int(token[6:].strip(",") or 0)
                elif token.startswith("behind "):
                    behind = int(token[7:].strip(",") or 0)
            continue
        code, path = line[:2], line[3:]
        if code == "??":
            untracked.append(path)
        elif code[0] not in " ?":
            staged.append({"code": code, "path": path})
        else:
            unstaged.append({"code": code, "path": path})
    return {
        "branch": branch,
        "ahead": ahead,
        "behind": behind,
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "clean": not (staged or unstaged or untracked),
    }


class _RootArgs(BaseModel):
    root: str = Field(default=".", description="repository working tree")


class GitStatus(BaseTool):
    name = "git.status"
    description = "Branch, ahead/behind, and staged/unstaged/untracked paths. Start here."
    danger = "safe"

    class Args(_RootArgs):
        pass

    def _run(self, a: GitStatus.Args) -> dict:
        return _status(a.root)


class GitDiff(BaseTool):
    name = "git.diff"
    description = "Unified diff of unstaged (or staged) changes, optionally for one path or ref."
    danger = "safe"

    class Args(_RootArgs):
        path: str | None = Field(default=None, description="limit the diff to this path")
        staged: bool = Field(default=False, description="diff the index against HEAD")
        ref: str | None = Field(default=None, description="diff against this commit or branch")

    def _run(self, a: GitDiff.Args) -> dict:
        argv = ["diff", "--no-color"]
        if a.staged:
            argv.append("--staged")
        if a.ref:
            argv.append(_ref(a.ref))
        if a.path:
            argv += ["--", _path(a.path)]
        out = _git(a.root, argv)
        return {"diff": out[:OUTPUT_LIMIT], "bytes": len(out), "truncated": len(out) > OUTPUT_LIMIT}


class GitLog(BaseTool):
    name = "git.log"
    description = "Recent commits (hash, author, date, subject), newest first."
    danger = "safe"

    class Args(_RootArgs):
        limit: int = Field(default=20, ge=1, le=200, description="how many commits")
        path: str | None = Field(default=None, description="only commits touching this path")

    def _run(self, a: GitLog.Args) -> dict:
        argv = [
            "log",
            "--no-color",
            "--date=short",
            "--format=%H%x1f%an%x1f%ad%x1f%s",
            "-n",
            str(a.limit),
        ]
        if a.path:
            argv += ["--", _path(a.path)]
        commits = []
        for line in _git(a.root, argv).splitlines():
            parts = line.split("\x1f")
            if len(parts) == 4:
                commits.append(
                    {"hash": parts[0], "author": parts[1], "date": parts[2], "subject": parts[3]}
                )
        return {"commits": commits, "count": len(commits)}


class GitShow(BaseTool):
    name = "git.show"
    description = "Show a commit, or one file at a ref (ref:path), without checking it out."
    danger = "safe"

    class Args(_RootArgs):
        ref: str = Field(default="HEAD", description="commit, branch, or tag")
        path: str | None = Field(default=None, description="file at that ref")

    def _run(self, a: GitShow.Args) -> dict:
        target = _ref(a.ref) + (":" + _path(a.path) if a.path else "")
        out = _git(a.root, ["show", "--no-color", target])
        return {
            "ref": a.ref,
            "content": out[:OUTPUT_LIMIT],
            "bytes": len(out),
            "truncated": len(out) > OUTPUT_LIMIT,
        }


class GitAdd(BaseTool):
    name = "git.add"
    description = "Stage paths for the next commit."
    danger = "sandboxed"

    class Args(_RootArgs):
        paths: list[str] = Field(min_length=1, max_length=200, description="paths to stage")

    def _run(self, a: GitAdd.Args) -> dict:
        _git(a.root, ["add", "--"] + [_path(p) for p in a.paths])
        return {"added": list(a.paths), "status": _status(a.root)}


class GitCommit(BaseTool):
    name = "git.commit"
    description = "Commit staged changes with a message; set all=true to stage tracked edits first."
    danger = "sandboxed"

    class Args(_RootArgs):
        message: str = Field(min_length=1, max_length=2000, description="commit message")
        all: bool = Field(default=False, description="stage tracked modifications first")

    def _run(self, a: GitCommit.Args) -> dict:
        argv = ["commit", "-m", a.message]
        if a.all:
            argv.append("--all")
        _git(a.root, argv)
        head = _git(a.root, ["log", "-1", "--format=%H%x1f%s"]).strip().split("\x1f")
        return {
            "hash": head[0] if head else "",
            "summary": head[1] if len(head) > 1 else "",
            "status": _status(a.root),
        }


class GitBranch(BaseTool):
    name = "git.branch"
    description = "List branches; with a name, create (create=true) or add a branch."
    danger = "sandboxed"

    class Args(_RootArgs):
        name: str | None = Field(default=None, description="branch to create")
        create: bool = Field(default=False, description="create and switch to it")

    def _run(self, a: GitBranch.Args) -> dict:
        if a.name and a.create:
            _git(a.root, ["checkout", "-b", _ref(a.name)])
        elif a.name:
            _git(a.root, ["branch", _ref(a.name)])
        out = _git(a.root, ["branch", "--format=%(refname:short)%09%(HEAD)"])
        branches = [
            {"name": line.split("\t")[0], "current": line.endswith("*")}
            for line in out.splitlines()
            if line.strip()
        ]
        return {
            "branches": branches,
            "current": next((b["name"] for b in branches if b["current"]), ""),
        }


class GitCheckout(BaseTool):
    name = "git.checkout"
    description = "Switch to an existing ref (branch, tag, or commit)."
    danger = "sandboxed"

    class Args(_RootArgs):
        ref: str = Field(min_length=1, description="ref to switch to")
        create: bool = Field(default=False, description="create the branch if it does not exist")

    def _run(self, a: GitCheckout.Args) -> dict:
        argv = ["checkout", "-b", _ref(a.ref)] if a.create else ["checkout", _ref(a.ref)]
        _git(a.root, argv)
        return {"current": _git(a.root, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()}
