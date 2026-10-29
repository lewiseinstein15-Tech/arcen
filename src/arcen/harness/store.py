"""A bounded local content-addressed object store; no refs or adoption yet.

This local API is not a sandbox against a hostile user with filesystem write
access. Object hashes are verified on every read and conflicting writes fail.
"""

from __future__ import annotations

import os
import re
import stat
import tempfile
from pathlib import Path

from .manifest import MAX_COMPONENT_BYTES, Manifest
from .model import canonical_manifest, content_hash, parse_manifest
from .resolver import HarnessError

_HASH = re.compile(r"[0-9a-f]{64}\Z")


class HarnessStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser()
        self.objects = self.root / "objects" / "sha256"
        for path in (self.root, self.root / "objects", self.objects):
            if path.is_symlink():
                raise HarnessError("store directories cannot be symlinks")
            try:
                path.mkdir(mode=0o700, parents=True, exist_ok=True)
            except OSError as exc:
                raise HarnessError("cannot create harness store") from exc
            if path.is_symlink() or not path.is_dir():
                raise HarnessError("invalid harness store directory")

    def _path(self, digest: str) -> Path:
        if type(digest) is not str or not _HASH.fullmatch(digest):
            raise HarnessError("invalid object hash")
        for path in (self.root, self.root / "objects", self.objects):
            if path.is_symlink() or not path.is_dir():
                raise HarnessError("invalid harness store directory")
        return self.objects / digest

    def get_blob(self, digest: str) -> bytes:
        path = self._path(digest)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            fd = os.open(path, flags)
            with os.fdopen(fd, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise HarnessError("stored object is not a regular file")
                data = stream.read(MAX_COMPONENT_BYTES + 1)
        except OSError as exc:
            raise HarnessError("cannot read stored object") from exc
        if len(data) > MAX_COMPONENT_BYTES or content_hash(data) != digest:
            raise HarnessError("stored object failed integrity check")
        return data

    def put_blob(self, data: bytes) -> str:
        if type(data) is not bytes or len(data) > MAX_COMPONENT_BYTES:
            raise HarnessError("invalid or oversized object")
        digest = content_hash(data)
        dest = self._path(digest)
        if dest.exists() or dest.is_symlink():
            self.get_blob(digest)
            return digest
        tmp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=self.objects, prefix=".tmp-", delete=False
            ) as stream:
                tmp_name = stream.name
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(tmp_name, dest, follow_symlinks=False)
            except FileExistsError:
                # Concurrent insertion must be valid, never silently replace.
                self.get_blob(digest)
        except OSError as exc:
            raise HarnessError("cannot write stored object") from exc
        finally:
            if tmp_name is not None:
                try:
                    os.unlink(tmp_name)
                except FileNotFoundError:
                    pass
        return digest

    def put_manifest(self, manifest: Manifest) -> str:
        data = canonical_manifest(manifest)
        # Only persist a complete manifest, with all components verified.
        for digest in manifest.components.values():
            self.get_blob(digest)
        return self.put_blob(data)

    def get_manifest(self, digest: str) -> Manifest:
        data = self.get_blob(digest)
        manifest = parse_manifest(data)
        if canonical_manifest(manifest) != data:
            raise HarnessError("stored manifest is not canonical")
        for component in manifest.components.values():
            self.get_blob(component)
        return manifest
