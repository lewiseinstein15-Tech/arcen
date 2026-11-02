"""Read a signed package blob from one explicit local Git commit.

This is a transport helper, not a Git-backed adoption store. The repository,
Git executable and local filesystem are trusted; a commit ID is not a signature
or proof of origin. No checkout, hook, working-tree read, network or ref write
is initiated here. The existing package verifier must still be used.
"""

from __future__ import annotations

import re
from pathlib import Path

from arcen.sandbox.workspace import WorkspaceError

from .package import MAX_PACKAGE_BYTES
from .probe_workspace import _run_git
from .resolver import HarnessError

_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_SEGMENT = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")
_OBJECT = re.compile(rb"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


def read_git_package(repo: str | Path, commit: str, path: str) -> bytes:
    """Return bounded committed blob bytes; caller must verify the signature.

    Accept only an exact full commit ID and literal ASCII path. Ref names,
    symlinks, submodules, working-tree paths, pathspec syntax and directories
    are rejected. No package, key, origin or content is trusted by this read.
    """
    if type(commit) is not str or _COMMIT.fullmatch(commit) is None:
        raise HarnessError("commit must be a full lowercase Git object ID")
    if type(path) is not str or not path or len(path) > 512:
        raise HarnessError("invalid committed package path")
    parts = path.split("/")
    if any(
        _SEGMENT.fullmatch(part) is None or part in {".", ".."} or part.lower() == ".git"
        for part in parts
    ):
        raise HarnessError("invalid committed package path")
    if not isinstance(repo, (str, Path)):
        raise HarnessError("invalid local Git repository")
    try:
        root = Path(repo).expanduser()
        if root.is_symlink():
            raise HarnessError("repository path cannot be a symlink")
        root = root.resolve(strict=True)
        if not root.is_dir():
            raise HarnessError("repository must be a directory")
        # Fail closed on Git versions without --no-lazy-fetch: promisor
        # repositories must never retrieve missing objects from a remote here.
        if (
            _run_git(root, ["--no-lazy-fetch", "cat-file", "-t", commit], max_bytes=128)
            != b"commit\n"
        ):
            raise HarnessError("Git object is not a commit")
        entry = _run_git(
            root,
            ["--no-lazy-fetch", "ls-tree", "-z", "--full-tree", commit, "--", path],
            max_bytes=1024,
        )
        # Exact mode/type/path check prevents accepting symlinks and gitlinks.
        chunks = entry.split(b"\0")
        if len(chunks) != 2 or chunks[1] != b"":
            raise HarnessError("committed package must be one regular file")
        header, separator, name = chunks[0].partition(b"\t")
        metadata = header.split(b" ")
        if (
            not separator
            or len(metadata) != 3
            or metadata[0] not in (b"100644", b"100755")
            or metadata[1] != b"blob"
            or _OBJECT.fullmatch(metadata[2]) is None
            or name != path.encode("ascii")
        ):
            raise HarnessError("committed package must be one regular file")
        # The blob ID was obtained from this immutable tree. Read by ID rather
        # than resolving the path again, then verify its package independently.
        return _run_git(
            root,
            ["--no-lazy-fetch", "cat-file", "blob", metadata[2].decode("ascii")],
            max_bytes=MAX_PACKAGE_BYTES,
        )
    except HarnessError:
        raise
    except (WorkspaceError, OSError, UnicodeError, ValueError, RuntimeError):
        raise HarnessError("cannot read committed package") from None
