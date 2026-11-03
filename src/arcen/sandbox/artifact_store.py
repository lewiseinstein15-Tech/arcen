"""Publish private, validated session patches; exporter integration is pending."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from pathlib import Path

from arcen.sandbox.patch_validation import ArtifactError, validate_patch

_BASE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _private_dir(parent_fd: int, name: str) -> int:
    try:
        os.mkdir(name, mode=0o700, dir_fd=parent_fd)
    except FileExistsError:
        pass
    fd = os.open(name, _FLAGS, dir_fd=parent_fd)
    info = os.fstat(fd)
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        os.close(fd)
        raise ArtifactError("artifact directory has unsafe ownership or permissions")
    return fd


def _write_private(dir_fd: int, name: str, data: bytes) -> None:
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dir_fd)
    with os.fdopen(fd, "wb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def save_artifact(
    session: str, patch: bytes, base_commit: str, *, home: Path | None = None
) -> dict:
    """Write a new session artifact once, failing closed on untrusted input.

    This does not obtain a protected snapshot baseline or run container export.
    """
    try:
        canonical = str(uuid.UUID(session))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ArtifactError("invalid session id") from exc
    if session != canonical:
        raise ArtifactError("session id must be canonical")
    if not isinstance(base_commit, str) or not _BASE.fullmatch(base_commit):
        raise ArtifactError("invalid base commit")
    paths = validate_patch(patch)
    digest = hashlib.sha256(patch).hexdigest()
    meta = {"base_commit": base_commit, "files": paths, "size": len(patch), "sha256": digest}
    data = (json.dumps(meta, sort_keys=True, separators=(",", ":")) + "\n").encode()
    root = (home or Path.home()).expanduser()
    fd_home = os.open(root, _FLAGS)
    fd_arcen = fd_artifacts = fd_session = None
    created = False
    try:
        home_info = os.fstat(fd_home)
        if home_info.st_uid != os.getuid() or home_info.st_mode & 0o022:
            raise ArtifactError("home directory has unsafe ownership or permissions")
        fd_arcen = _private_dir(fd_home, ".arcen")
        fd_artifacts = _private_dir(fd_arcen, "artifacts")
        try:
            os.mkdir(canonical, mode=0o700, dir_fd=fd_artifacts)
        except FileExistsError as exc:
            raise ArtifactError("session artifact already exists") from exc
        created = True
        fd_session = os.open(canonical, _FLAGS, dir_fd=fd_artifacts)
        info = os.fstat(fd_session)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ArtifactError("session artifact directory is not private")
        _write_private(fd_session, "patch.diff", patch)
        _write_private(fd_session, "meta.json", data)
        os.fsync(fd_session)
        os.fsync(fd_artifacts)
    except BaseException:
        if created and fd_session is not None and fd_artifacts is not None:
            for name in ("patch.diff", "meta.json"):
                try:
                    os.unlink(name, dir_fd=fd_session)
                except FileNotFoundError:
                    pass
            os.rmdir(canonical, dir_fd=fd_artifacts)
        raise
    finally:
        for fd in (fd_session, fd_artifacts, fd_arcen, fd_home):
            if fd is not None:
                os.close(fd)
    return {**meta, "path": str(root / ".arcen" / "artifacts" / canonical / "patch.diff")}


def publish_artifact(
    session: str, patch: bytes, base_commit: str, emit, *, home: Path | None = None
) -> dict:
    """Save first, then notify using the existing file.diff event.

    No event is emitted when validation or storage fails. This is not wired to
    server turns until a trusted inside-container exporter exists.
    """
    from arcen.stream.events import FileDiff

    result = save_artifact(session, patch, base_commit, home=home)
    artifact = {"path": result["path"], "files": result["files"], "sha256": result["sha256"]}
    emit(FileDiff(seq=0, path=result["path"], patch="", artifact=artifact, ts=0.0))
    return result
