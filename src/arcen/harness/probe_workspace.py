"""Bounded input snapshots for probes from an explicit local Git commit.

The Git process is a fixed local archive command, not model-provided code. No
working tree files, untracked files, .git directory or host mounts are copied.
The source repository and Git executable are trusted local inputs; committed
files may still contain secrets, and a filename denylist cannot detect them all.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import selectors
import signal
import subprocess
import tarfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from arcen.guardrails import default_policy
from arcen.sandbox.workspace import MAX_BYTES, MAX_FILES, WorkspaceError

_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_GIT = "/usr/bin/git"
_TIMEOUT = 30.0
_MAX_TAR_OVERHEAD = 16 * 1024 * 1024
_SECRET_DIRS = frozenset({".ssh", ".gnupg", ".aws", ".kube", ".azure", ".config"})
_SECRET_NAMES = frozenset(
    {".netrc", ".npmrc", ".pypirc", "id_rsa", "id_ed25519", "credentials", "credentials.json"}
)


@dataclass(frozen=True, slots=True)
class GitSnapshot:
    commit: str
    sha256: str
    entries: int
    file_bytes: int
    archive: bytes = field(repr=False)


def _run_git(repo: Path, args: list[str], *, max_bytes: int) -> bytes:
    """Read bounded Git output with timeout; never invoke a shell or network."""
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/nonexistent",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
    }
    try:
        proc = subprocess.Popen(
            [_GIT, "-C", str(repo), *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
    except OSError as exc:
        raise WorkspaceError("cannot start local Git") from exc
    assert proc.stdout is not None
    out = bytearray()
    deadline = time.monotonic() + _TIMEOUT
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise WorkspaceError("Git snapshot timed out")
                if not selector.select(remaining):
                    raise WorkspaceError("Git snapshot timed out")
                chunk = os.read(proc.stdout.fileno(), min(65536, max_bytes + 1 - len(out)))
                if not chunk:
                    break
                out.extend(chunk)
                if len(out) > max_bytes:
                    raise WorkspaceError("Git snapshot output exceeds limit")
        remaining = max(0.0, deadline - time.monotonic())
        if proc.wait(timeout=remaining) != 0:
            raise WorkspaceError("local Git could not archive the selected commit")
    except (WorkspaceError, subprocess.TimeoutExpired) as exc:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
        if isinstance(exc, WorkspaceError):
            raise
        raise WorkspaceError("Git snapshot timed out") from exc
    finally:
        proc.stdout.close()
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
    return bytes(out)


def _safe_name(name: str, is_dir: bool) -> str:
    if type(name) is not str or not name or len(name.encode("utf-8")) > 4096 or "\\" in name:
        raise WorkspaceError("invalid archive path")
    trimmed = name[:-1] if is_dir and name.endswith("/") else name
    pieces = trimmed.split("/")
    if trimmed.startswith("/") or any(part in ("", ".", "..") for part in pieces):
        raise WorkspaceError("unsafe archive path")
    if PurePosixPath(trimmed).is_absolute():
        raise WorkspaceError("unsafe archive path")
    folded = [part.lower() for part in pieces]
    if any(part in _SECRET_DIRS or part == ".git" for part in folded):
        raise WorkspaceError("archive contains a protected credential directory")
    leaf = folded[-1]
    if (
        leaf in _SECRET_NAMES
        or leaf == ".env"
        or leaf.startswith(".env.")
        or leaf.endswith((".pem", ".p12", ".pfx", ".key"))
    ):
        raise WorkspaceError("archive contains a protected credential filename")
    return trimmed


def snapshot_git_commit(repo: str | Path, commit: str) -> GitSnapshot:
    """Snapshot tracked files from a full commit ID into a normalized tar.

    This function never runs project code and rejects symlinks, submodules,
    special files, suspicious credential paths and resource-limit violations.
    Filenames are not a secret scanner: only use reviewed commits containing
    no credentials or other data inappropriate to expose to a model/provider.
    """
    if type(commit) is not str or not _COMMIT.fullmatch(commit):
        raise WorkspaceError("commit must be a full lowercase Git object ID")
    path = Path(repo).expanduser()
    if path.is_symlink():
        raise WorkspaceError("repository path cannot be a symlink")
    try:
        path = path.resolve(strict=True)
    except OSError as exc:
        raise WorkspaceError("cannot read repository") from exc
    if not path.is_dir():
        raise WorkspaceError("repository must be a directory")
    if _run_git(path, ["cat-file", "-t", commit], max_bytes=128) != b"commit\n":
        raise WorkspaceError("Git object is not a commit")
    limits = default_policy().workspace
    limit_entries = min(limits.max_entries, MAX_FILES)
    limit_bytes = min(limits.max_file_bytes, MAX_BYTES)
    raw = _run_git(
        path, ["archive", "--format=tar", commit], max_bytes=limit_bytes + _MAX_TAR_OVERHEAD
    )
    result = io.BytesIO()
    names: set[str] = set()
    count = total = 0
    try:
        with (
            tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as src,
            tarfile.open(fileobj=result, mode="w") as dst,
        ):
            for item in src:
                count += 1
                if count > limit_entries:
                    raise WorkspaceError("Git snapshot exceeds entry limit")
                if not (item.isdir() or item.isfile()) or item.sparse is not None:
                    raise WorkspaceError("Git snapshot contains a link or special file")
                name = _safe_name(item.name, item.isdir())
                if name in names:
                    raise WorkspaceError("Git snapshot contains duplicate entries")
                names.add(name)
                entry = tarfile.TarInfo(name)
                entry.uid = entry.gid = 65534
                entry.uname = entry.gname = ""
                entry.mtime = 0
                if item.isdir():
                    entry.type = tarfile.DIRTYPE
                    entry.mode = 0o755
                    dst.addfile(entry)
                else:
                    if item.size < 0:
                        raise WorkspaceError("invalid Git snapshot file size")
                    total += item.size
                    if total > limit_bytes:
                        raise WorkspaceError("Git snapshot exceeds file-byte limit")
                    source = src.extractfile(item)
                    if source is None:
                        raise WorkspaceError("missing Git snapshot file")
                    entry.size = item.size
                    entry.mode = 0o755 if item.mode & 0o111 else 0o644
                    with source:
                        dst.addfile(entry, source)
    except (tarfile.TarError, OSError, UnicodeError, ValueError) as exc:
        if isinstance(exc, WorkspaceError):
            raise
        raise WorkspaceError("invalid Git archive") from exc
    archive = result.getvalue()
    return GitSnapshot(commit, hashlib.sha256(archive).hexdigest(), count, total, archive)


@contextmanager
def materialize_git_snapshot(snapshot: GitSnapshot):
    """Create a short-lived private input tree from a verified snapshot.

    The caller may pass the yielded directory to the Docker-only workspace
    importer. This is not a probe runner and executes none of the tree's code.
    Cleanup is automatic. Revalidate even though snapshots are frozen: callers
    can construct a GitSnapshot directly rather than using snapshot_git_commit.
    """
    import tempfile

    if (
        type(snapshot) is not GitSnapshot
        or type(snapshot.commit) is not str
        or not _COMMIT.fullmatch(snapshot.commit)
        or type(snapshot.sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", snapshot.sha256) is None
        or type(snapshot.entries) is not int
        or snapshot.entries < 0
        or type(snapshot.file_bytes) is not int
        or snapshot.file_bytes < 0
    ):
        raise WorkspaceError("invalid Git snapshot")
    limits = default_policy().workspace
    max_bytes = min(limits.max_file_bytes, MAX_BYTES)
    max_entries = min(limits.max_entries, MAX_FILES)
    data = snapshot.archive
    if type(data) is not bytes or len(data) > max_bytes + _MAX_TAR_OVERHEAD:
        raise WorkspaceError("Git snapshot archive exceeds limit")
    if hashlib.sha256(data).hexdigest() != snapshot.sha256:
        raise WorkspaceError("Git snapshot integrity check failed")
    names: set[str] = set()
    count = total = 0
    with tempfile.TemporaryDirectory(prefix="arcen-probe-input-") as directory:
        root = Path(directory)
        try:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
                for item in archive:
                    count += 1
                    if count > max_entries:
                        raise WorkspaceError("Git snapshot exceeds entry limit")
                    if not (item.isdir() or item.isfile()) or item.sparse is not None:
                        raise WorkspaceError("Git snapshot contains a link or special file")
                    name = _safe_name(item.name, item.isdir())
                    if name in names:
                        raise WorkspaceError("Git snapshot contains duplicate entries")
                    names.add(name)
                    target = root.joinpath(*name.split("/"))
                    if item.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        total += item.size
                        if item.size < 0 or total > max_bytes:
                            raise WorkspaceError("Git snapshot exceeds file-byte limit")
                        target.parent.mkdir(parents=True, exist_ok=True)
                        source = archive.extractfile(item)
                        if source is None:
                            raise WorkspaceError("missing Git snapshot file")
                        with source, target.open("xb") as dest:
                            remaining = item.size
                            while remaining:
                                chunk = source.read(min(65536, remaining))
                                if not chunk:
                                    raise WorkspaceError("incomplete Git snapshot file")
                                dest.write(chunk)
                                remaining -= len(chunk)
                        target.chmod(0o755 if item.mode & 0o111 else 0o644)
        except (tarfile.TarError, OSError, UnicodeError, ValueError) as exc:
            if isinstance(exc, WorkspaceError):
                raise
            raise WorkspaceError("invalid Git snapshot archive") from exc
        if count != snapshot.entries or total != snapshot.file_bytes:
            raise WorkspaceError("Git snapshot metadata mismatch")
        yield root
