"""Create bounded input-only workspace snapshots without host bind mounts.

Explicit ``--workspace`` includes all regular files, including dotfiles and
possibly secrets. It rejects symlinks, special files, and oversized trees.
No container output is copied back to the host.
"""

from __future__ import annotations

import io
import os
import stat
import tarfile
from pathlib import Path

MAX_FILES = 10_000
MAX_BYTES = 64 * 1024 * 1024


class WorkspaceError(ValueError):
    """A workspace cannot safely be imported."""


def snapshot_workspace(
    path: str | Path, *, max_entries: int | None = None, max_file_bytes: int | None = None
) -> bytes:
    max_entries = MAX_FILES if max_entries is None else max_entries
    max_file_bytes = MAX_BYTES if max_file_bytes is None else max_file_bytes
    if not 0 <= max_entries <= MAX_FILES or not 0 <= max_file_bytes <= MAX_BYTES:
        raise WorkspaceError("workspace limits exceed the immutable safety caps")
    root = Path(path).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise WorkspaceError("workspace must be a directory")
    out = io.BytesIO()
    count = 0
    size = 0

    def fail_walk(exc: OSError) -> None:
        raise exc

    with tarfile.open(fileobj=out, mode="w") as archive:
        # fwalk anchors each lookup to an open directory descriptor and never
        # follows directory symlinks. O_NOFOLLOW also protects final filenames.
        for current, dirs, files, dirfd in os.fwalk(root, follow_symlinks=False, onerror=fail_walk):
            dirs.sort()
            files.sort()
            for name in dirs + files:
                count += 1
                if count > max_entries:
                    raise WorkspaceError(f"workspace exceeds {max_entries} entries")
                info = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
                relative = (Path(current).relative_to(root) / name).as_posix()
                if stat.S_ISLNK(info.st_mode):
                    raise WorkspaceError(f"workspace contains a symlink: {relative}")
                entry = tarfile.TarInfo(relative)
                entry.uid = entry.gid = 65534
                entry.uname = entry.gname = ""
                entry.mtime = 0
                if stat.S_ISDIR(info.st_mode):
                    entry.type = tarfile.DIRTYPE
                    entry.mode = 0o755
                    archive.addfile(entry)
                elif stat.S_ISREG(info.st_mode):
                    size += info.st_size
                    if size > max_file_bytes:
                        raise WorkspaceError(f"workspace exceeds {max_file_bytes} file bytes")
                    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dirfd)
                    with os.fdopen(fd, "rb") as source:
                        opened = os.fstat(source.fileno())
                        if (opened.st_dev, opened.st_ino, opened.st_size) != (
                            info.st_dev,
                            info.st_ino,
                            info.st_size,
                        ) or not stat.S_ISREG(opened.st_mode):
                            raise WorkspaceError(f"workspace changed during snapshot: {relative}")
                        entry.size = opened.st_size
                        entry.mode = 0o755 if info.st_mode & 0o111 else 0o644
                        archive.addfile(entry, source)
                else:
                    raise WorkspaceError(f"workspace contains a special file: {relative}")
    return out.getvalue()


# Executed inside the disposable container as UID 65534, with cwd=/workspace.
# It reads exactly the expected archive length, so no socket half-close is
# needed. No shell or model-provided script is involved. The host generated
# this archive, but the extractor validates member types and paths again.
CONTAINER_IMPORTER = r"""
import io
import os
import pathlib
import shutil
import sys
import tarfile

size = int(sys.argv[1])
data = sys.stdin.buffer.read(size)
if len(data) != size:
    raise RuntimeError("incomplete workspace archive")
root = pathlib.Path.cwd()
seen = set()
with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
    for item in archive:
        path = pathlib.PurePosixPath(item.name)
        if path.is_absolute() or not path.parts or ".." in path.parts or item.name in seen:
            raise ValueError("unsafe workspace entry")
        seen.add(item.name)
        target = root.joinpath(*path.parts)
        if item.isdir():
            target.mkdir(parents=True, exist_ok=True)
        elif item.isfile():
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(item)
            if source is None:
                raise ValueError("missing workspace data")
            with source, target.open("xb") as dest:
                shutil.copyfileobj(source, dest)
            os.chmod(target, 0o755 if item.mode & 0o111 else 0o644)
        else:
            raise ValueError("unsupported workspace entry")
"""


def import_workspace(client, container, archive: bytes) -> None:
    """Stream a safe snapshot into tmpfs without Docker's put_archive API.

    Docker rejects put_archive when the rootfs is read-only, including paths
    on writable tmpfs mounts. Instead, an unprivileged container process reads
    the bounded archive over an attached exec stdin and extracts into its own
    /workspace. Failure must abort the turn; the caller removes the container.
    """
    api = client.api
    created = api.exec_create(
        container.id,
        cmd=[
            "timeout",
            "--kill-after=2s",
            "120s",
            "python",
            "-c",
            CONTAINER_IMPORTER,
            str(len(archive)),
        ],
        stdin=True,
        user="65534:65534",
        privileged=False,
        workdir="/workspace",
        environment={"HOME": "/tmp", "LANG": "C.UTF-8", "PATH": "/usr/local/bin:/usr/bin:/bin"},
    )
    exec_id = created["Id"]
    connection = api.exec_start(exec_id, socket=True)
    try:
        # docker-py's Unix transport returns socket.SocketIO, whereas TCP,
        # TLS and SSH transports can return socket-like objects directly.
        sock = getattr(connection, "_sock", connection)
        sock.settimeout(130)
        sock.sendall(archive)
        received = 0
        while chunk := sock.recv(4096):
            received += len(chunk)
            if received > 65536:
                raise WorkspaceError("workspace importer output exceeded limit")
    finally:
        response = getattr(connection, "_response", None)
        if response is not None:
            response.close()
        connection.close()
    if api.exec_inspect(exec_id).get("ExitCode") != 0:
        raise WorkspaceError("workspace importer failed")
