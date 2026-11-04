"""Explicit, dry-run-by-default application of validated session artifacts.

A-03 export is not yet implemented. This command can only apply an existing
artifact that passes integrity, base and dirty-path checks.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import uuid
from pathlib import Path

from arcen.sandbox.patch_validation import MAX_PATCH_BYTES, ArtifactError, validate_patch

_BASE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _open_dir(parent: int, name: str, *, private: bool = False) -> int:
    fd = os.open(name, _DIR_FLAGS, dir_fd=parent)
    info = os.fstat(fd)
    unsafe = 0o077 if private else 0o022
    if info.st_uid != os.getuid() or info.st_mode & unsafe:
        os.close(fd)
        raise ArtifactError("artifact directory has unsafe ownership or permissions")
    return fd


def _read_private(parent: int, name: str, limit: int) -> bytes:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or info.st_nlink != 1
        ):
            raise ArtifactError("artifact file is not private")
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ArtifactError(f"artifact {name} exceeds size limit")
        return data


def load_artifact(session: str, *, home: Path | None = None) -> tuple[bytes, dict]:
    try:
        canonical = str(uuid.UUID(session))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ArtifactError("invalid session id") from exc
    if session != canonical:
        raise ArtifactError("session id must be canonical")
    fds = []
    try:
        home_fd = os.open((home or Path.home()).expanduser(), _DIR_FLAGS)
        fds.append(home_fd)
        info = os.fstat(home_fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ArtifactError("home directory has unsafe ownership or permissions")
        current = home_fd
        for name in (".arcen", "artifacts", canonical):
            current = _open_dir(current, name, private=name == canonical)
            fds.append(current)
        patch = _read_private(current, "patch.diff", MAX_PATCH_BYTES)
        raw_meta = _read_private(current, "meta.json", 64 * 1024)
    except OSError as exc:
        raise ArtifactError("artifact could not be safely opened") from exc
    finally:
        for fd in reversed(fds):
            os.close(fd)
    try:
        meta = json.loads(raw_meta)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ArtifactError("invalid artifact metadata") from exc
    if not isinstance(meta, dict) or set(meta) != {"base_commit", "files", "size", "sha256"}:
        raise ArtifactError("invalid artifact metadata")
    if not isinstance(meta["base_commit"], str) or not _BASE.fullmatch(meta["base_commit"]):
        raise ArtifactError("invalid artifact base commit")
    if not isinstance(meta["sha256"], str) or not _SHA256.fullmatch(meta["sha256"]):
        raise ArtifactError("invalid artifact hash")
    if type(meta["size"]) is not int or meta["size"] != len(patch):
        raise ArtifactError("artifact size mismatch")
    if hashlib.sha256(patch).hexdigest() != meta["sha256"]:
        raise ArtifactError("artifact hash mismatch")
    if meta["files"] != validate_patch(patch):
        raise ArtifactError("artifact file list mismatch")
    return patch, meta


def _git(root: Path, *args: str, data: bytes | None = None) -> bytes:
    env = {
        "PATH": os.defpath,
        "HOME": "/nonexistent",
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
    }
    argv = [
        "git",
        "--no-optional-locks",
        "--literal-pathspecs",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.attributesFile=/dev/null",
        "-C",
        str(root),
        *args,
    ]
    try:
        result = subprocess.run(
            argv, input=data, capture_output=True, env=env, timeout=120, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ArtifactError("git command could not be completed") from exc
    if result.returncode:
        raise ArtifactError(
            "git command failed: " + result.stderr.decode("utf-8", "replace").strip()[:500]
        )
    return result.stdout


def apply_artifact(
    session: str,
    *,
    target: Path,
    yes: bool = False,
    allow_different_base: bool = False,
    home: Path | None = None,
) -> dict:
    patch, meta = load_artifact(session, home=home)
    root = Path(
        os.fsdecode(_git(target, "rev-parse", "--show-toplevel").removesuffix(b"\n"))
    ).resolve(strict=True)
    current = _git(root, "rev-parse", "--verify", "HEAD").decode("ascii").strip()
    if current != meta["base_commit"] and not allow_different_base:
        raise ArtifactError(
            "target HEAD differs from artifact base; use --allow-different-base to override"
        )
    files = meta["files"]
    if files:
        attrs = _git(root, "check-attr", "-z", "filter", "--", *files).split(b"\0")
        if len(attrs) != 3 * len(files) + 1 or any(
            attrs[i] not in (b"unspecified", b"unset") for i in range(2, len(attrs) - 1, 3)
        ):
            raise ArtifactError("target paths have Git filters; refusing to run host filters")
        flags = _git(root, "ls-files", "-v", "-z", "--", *files)
        if any(not item.startswith(b"H ") for item in flags.split(b"\0") if item):
            raise ArtifactError("target has assume-unchanged or skip-worktree paths")
        dirty = _git(
            root,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignored",
            "--",
            *files,
        )
        if dirty:
            raise ArtifactError("target has uncommitted or untracked changes to artifact files")
        _git(root, "apply", "--check", "--", "-", data=patch)
        if yes:
            _git(root, "apply", "--", "-", data=patch)
    return {"files": files, "applied": bool(yes and files), "base_commit": meta["base_commit"]}
