"""Untrusted workspace archive validation and isolated Git patch construction.

The helpers in this module do not export an artifact or apply a patch; server
integration and secure artifact publication are separate work in progress.
"""

from __future__ import annotations

import io
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

MAX_ENTRIES = 10_000
MAX_BYTES = 64 * 1024 * 1024
MAX_PATCH_BYTES = 128 * 1024 * 1024


class ArtifactError(ValueError):
    """Untrusted workspace data cannot be safely turned into a patch."""


def archive_files(data: bytes, *, prefix: str = "") -> dict[str, tuple[bytes, int]]:
    """Read only safe regular files, never extract untrusted tar paths."""
    if len(data) > MAX_BYTES + 16 * 1024 * 1024:
        raise ArtifactError("workspace archive exceeds size limit")
    result: dict[str, tuple[bytes, int]] = {}
    seen: set[str] = set()
    total = count = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tar:
            for item in tar:
                count += 1
                if count > MAX_ENTRIES:
                    raise ArtifactError("workspace has too many entries")
                name = item.name
                parts = PurePosixPath(name).parts
                if (
                    not parts
                    or name.startswith("/")
                    or ".." in parts
                    or "\\" in name
                    or len(name.encode("utf-8")) > 1024
                    or any(ord(c) < 32 or ord(c) == 127 for c in name)
                ):
                    raise ArtifactError("unsafe workspace path")
                if prefix:
                    if parts[0] != prefix:
                        raise ArtifactError("archive escaped workspace root")
                    parts = parts[1:]
                if not parts:
                    if item.isdir():
                        continue
                    raise ArtifactError("workspace root must be a directory")
                path = "/".join(parts)
                if path in seen:
                    raise ArtifactError("duplicate workspace path")
                seen.add(path)
                if any(part.lower() == ".git" for part in parts):
                    continue
                if item.isdir():
                    continue
                if not item.isfile() or item.issym() or item.islnk():
                    raise ArtifactError("workspace contains a link or special file")
                total += item.size
                if item.size < 0 or total > MAX_BYTES:
                    raise ArtifactError("workspace file bytes exceed limit")
                stream = tar.extractfile(item)
                if stream is None:
                    raise ArtifactError("workspace file has no data")
                content = stream.read(item.size + 1)
                if len(content) != item.size:
                    raise ArtifactError("workspace archive is truncated")
                result[path] = (content, 0o100755 if item.mode & 0o111 else 0o100644)
    except (tarfile.TarError, OSError, UnicodeError) as exc:
        raise ArtifactError("invalid workspace archive") from exc
    return result


def build_patch(before_archive: bytes | None, after_archive: bytes) -> tuple[bytes, list[str]]:
    """Construct a binary-capable git diff in a private throwaway repository."""
    before = archive_files(before_archive) if before_archive is not None else {}
    after = archive_files(after_archive, prefix="workspace")
    paths = sorted(
        name for name in before.keys() | after.keys() if before.get(name) != after.get(name)
    )
    if not paths:
        return b"", []
    with tempfile.TemporaryDirectory(prefix="arcen-patch-") as tmp:
        root = Path(tmp)
        repo = root / "repo"
        repo.mkdir()
        env = {
            "PATH": os.defpath,
            "HOME": str(root),
            "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        }

        def git(*args: str, data: bytes | None = None) -> bytes:
            try:
                with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                    subprocess.run(
                        ["git", "-C", str(repo), *args],
                        input=data,
                        stdout=stdout,
                        stderr=stderr,
                        env=env,
                        timeout=120,
                        check=True,
                    )
                    if stdout.tell() > MAX_PATCH_BYTES:
                        raise ArtifactError("git output exceeds size limit")
                    stdout.seek(0)
                    return stdout.read()
            except (subprocess.SubprocessError, OSError) as exc:
                raise ArtifactError("isolated git operation failed") from exc

        git("init", "-q")

        def tree(files: dict[str, tuple[bytes, int]], label: str) -> str:
            directory = root / label
            directory.mkdir()
            names = sorted(files)
            for name in names:
                target = directory.joinpath(*name.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(files[name][0])
            if names:
                filename_bytes = b"".join(os.fsencode(directory / name) + b"\n" for name in names)
                hashes = git(
                    "hash-object", "-w", "--no-filters", "--stdin-paths", data=filename_bytes
                ).splitlines()
                if len(hashes) != len(names):
                    raise ArtifactError("git returned an incomplete object list")
            else:
                hashes = []
            git("read-tree", "--empty")
            if names:
                index = b"".join(
                    f"{files[name][1]:o} ".encode() + oid + b"\t" + name.encode() + b"\0"
                    for name, oid in zip(names, hashes, strict=True)
                )
                git("update-index", "-z", "--index-info", data=index)
            return git("write-tree").decode("ascii").strip()

        old_tree = tree(before, "before")
        new_tree = tree(after, "after")
        patch = git(
            "diff",
            "--binary",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            old_tree,
            new_tree,
            "--",
        )
        if len(patch) > MAX_PATCH_BYTES:
            raise ArtifactError("patch exceeds size limit")
        return patch, paths
