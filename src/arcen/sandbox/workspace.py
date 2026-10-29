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


def snapshot_workspace(path: str | Path) -> bytes:
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
                if count > MAX_FILES:
                    raise WorkspaceError(f"workspace exceeds {MAX_FILES} entries")
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
                    if size > MAX_BYTES:
                        raise WorkspaceError("workspace exceeds 64 MiB")
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
