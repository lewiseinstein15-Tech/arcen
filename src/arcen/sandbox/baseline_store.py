"""Persist a private host-only snapshot before a disposable turn.

Not yet wired to DockerTurnRegistry; never mount this directory in a sandbox.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import uuid
from pathlib import Path

from arcen.sandbox.artifact_store import _FLAGS, _private_dir, _write_private
from arcen.sandbox.host_export import extract_candidate
from arcen.sandbox.patch_validation import ArtifactError

_BASE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


def save_baseline(
    session: str, snapshot: bytes, base_commit: str, *, home: Path | None = None
) -> Path:
    """Persist an immutable-by-container archive in a new private session directory."""
    try:
        canonical = str(uuid.UUID(session))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ArtifactError("invalid session id") from exc
    if canonical != session:
        raise ArtifactError("session id must be canonical")
    if not isinstance(base_commit, str) or not _BASE.fullmatch(base_commit):
        raise ArtifactError("invalid base commit")
    # Extract into a private temporary directory before persisting any bytes.
    with tempfile.TemporaryDirectory(prefix="arcen-baseline-check-") as temporary:
        extract_candidate(snapshot, Path(temporary) / "snapshot")
    metadata = {
        "base_commit": base_commit,
        "sha256": hashlib.sha256(snapshot).hexdigest(),
        "size": len(snapshot),
    }
    raw_meta = (json.dumps(metadata, sort_keys=True) + "\n").encode()
    root = (home or Path.home()).expanduser()
    fds: list[int] = []
    session_fd = baseline_fd = artifacts_fd = None
    created = False
    try:
        fd = os.open(root, _FLAGS)
        fds.append(fd)
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ArtifactError("home directory has unsafe ownership or permissions")
        fd = _private_dir(fd, ".arcen")
        fds.append(fd)
        artifacts_fd = _private_dir(fd, "artifacts")
        fds.append(artifacts_fd)
        try:
            os.mkdir(canonical, mode=0o700, dir_fd=artifacts_fd)
        except FileExistsError as exc:
            raise ArtifactError("session artifact already exists") from exc
        created = True
        session_fd = os.open(canonical, _FLAGS, dir_fd=artifacts_fd)
        fds.append(session_fd)
        os.mkdir("baseline", mode=0o700, dir_fd=session_fd)
        baseline_fd = os.open("baseline", _FLAGS, dir_fd=session_fd)
        fds.append(baseline_fd)
        info = os.fstat(baseline_fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ArtifactError("baseline directory is not private")
        _write_private(baseline_fd, "snapshot.tar", snapshot)
        _write_private(baseline_fd, "baseline.json", raw_meta)
        os.fsync(baseline_fd)
        os.fsync(session_fd)
        os.fsync(artifacts_fd)
    except BaseException:
        if baseline_fd is not None:
            for name in ("snapshot.tar", "baseline.json"):
                try:
                    os.unlink(name, dir_fd=baseline_fd)
                except FileNotFoundError:
                    pass
        if session_fd is not None:
            try:
                os.rmdir("baseline", dir_fd=session_fd)
            except FileNotFoundError:
                pass
        if created and artifacts_fd is not None:
            os.rmdir(canonical, dir_fd=artifacts_fd)
        raise
    finally:
        for fd in reversed(fds):
            os.close(fd)
    return root / ".arcen" / "artifacts" / canonical / "baseline"


def load_baseline(session: str, *, home: Path | None = None) -> tuple[bytes, str]:
    """Reopen a baseline without symlink traversal and verify its metadata."""
    from arcen.sandbox.artifact_apply import _open_dir, _read_private
    from arcen.sandbox.patch_validation import MAX_PATCH_BYTES

    try:
        canonical = str(uuid.UUID(session))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ArtifactError("invalid session id") from exc
    if canonical != session:
        raise ArtifactError("session id must be canonical")
    fds = []
    try:
        root = (home or Path.home()).expanduser()
        fd = os.open(root, _FLAGS)
        fds.append(fd)
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ArtifactError("home directory has unsafe ownership or permissions")
        for name in (".arcen", "artifacts", canonical, "baseline"):
            fd = _open_dir(fd, name, private=name in (canonical, "baseline"))
            fds.append(fd)
        snapshot = _read_private(fd, "snapshot.tar", MAX_PATCH_BYTES)
        raw = _read_private(fd, "baseline.json", 4096)
    except OSError as exc:
        raise ArtifactError("baseline could not be safely opened") from exc
    finally:
        for fd in reversed(fds):
            os.close(fd)
    try:
        meta = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ArtifactError("invalid baseline metadata") from exc
    if not isinstance(meta, dict) or set(meta) != {"base_commit", "sha256", "size"}:
        raise ArtifactError("invalid baseline metadata")
    if not isinstance(meta["base_commit"], str) or not _BASE.fullmatch(meta["base_commit"]):
        raise ArtifactError("invalid baseline base commit")
    if type(meta["size"]) is not int or meta["size"] != len(snapshot):
        raise ArtifactError("baseline size mismatch")
    if (
        not isinstance(meta["sha256"], str)
        or hashlib.sha256(snapshot).hexdigest() != meta["sha256"]
    ):
        raise ArtifactError("baseline hash mismatch")
    return snapshot, meta["base_commit"]


def capture_workspace_baseline(
    session: str, workspace: str | Path, *, home: Path | None = None
) -> tuple[bytes, str]:
    """Capture one Git-root working tree on the host before launching a turn.

    The repository, Git executable and local configuration are trusted host
    inputs. The returned bytes are exactly the bytes intended for container
    import; the private saved baseline is never passed as a host mount.
    """
    import os

    from arcen.harness.probe_workspace import _reject_configured_git_filters, _run_git
    from arcen.sandbox.workspace import snapshot_workspace

    try:
        root = Path(workspace).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ArtifactError("workspace must be a Git root directory")
        top = Path(
            os.fsdecode(_run_git(root, ["rev-parse", "--show-toplevel"], max_bytes=4096)).strip()
        )
        if top.resolve(strict=True) != root:
            raise ArtifactError("workspace must be the Git root directory")
        _reject_configured_git_filters(root)
        base = (
            _run_git(root, ["rev-parse", "--verify", "HEAD^{commit}"], max_bytes=128)
            .decode("ascii")
            .strip()
        )
        if not _BASE.fullmatch(base):
            raise ArtifactError("invalid workspace HEAD")
        snapshot = snapshot_workspace(root, exclude_git=True)
        after = (
            _run_git(root, ["rev-parse", "--verify", "HEAD^{commit}"], max_bytes=128)
            .decode("ascii")
            .strip()
        )
        if after != base:
            raise ArtifactError("workspace HEAD changed during baseline capture")
        save_baseline(session, snapshot, base, home=home)
        return snapshot, base
    except (OSError, UnicodeError) as exc:
        raise ArtifactError("workspace baseline capture failed") from exc
