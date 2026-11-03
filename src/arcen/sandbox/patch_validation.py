"""Conservative validation of untrusted, canonical Git binary patches.

This is an A-03 building block, not an export or apply implementation.  Paths
outside the deliberately small supported character set fail closed rather than
being interpreted differently by Git and by the artifact validator.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath


class ArtifactError(ValueError):
    """An artifact or untrusted patch is not safe to use."""


MAX_PATCH_BYTES = 5 * 1024 * 1024
_SAFE_PATH = re.compile(rb"[A-Za-z0-9_.+/-]+\Z")
_HEADER = re.compile(rb"diff --git a/([^ ]+) b/([^ ]+)\Z")


def _path(raw: bytes) -> str:
    if not _SAFE_PATH.fullmatch(raw):
        raise ArtifactError("unsupported or unsafe patch path")
    path = raw.decode("ascii")
    parts = path.split("/")
    if (
        path.startswith("/")
        or any(part in ("", ".", "..") for part in parts)
        or any(part.lower() == ".git" for part in parts)
        or any(
            part.lower().startswith(".env")
            or part.lower() in {".npmrc", ".pypirc", ".gitattributes", ".gitmodules"}
            or part.lower().endswith((".pem", ".key", ".p12"))
            or part.lower().startswith("id_")
            for part in parts
        )
        or PurePosixPath(path).is_absolute()
    ):
        raise ArtifactError("unsafe or secret patch path")
    return path


def validate_patch(patch: bytes) -> list[str]:
    """Return changed relative paths, rejecting unsafe and ambiguous patches.

    Only canonical, no-renames Git output is supported. Git quoted names and
    metadata operations such as renames and copies are deliberately rejected.
    This function does not assert that a patch will apply or publish anything.
    """
    if len(patch) > MAX_PATCH_BYTES:
        raise ArtifactError(f"patch exceeds {MAX_PATCH_BYTES} byte limit")
    if not patch:
        return []
    if b"\0" in patch or not patch.endswith(b"\n"):
        raise ArtifactError("invalid patch encoding or termination")
    files: list[str] = []
    current: bytes | None = None
    in_body = False
    minus = plus = False
    executable = False
    for line in patch.splitlines():
        if line.startswith(b"diff --git "):
            match = _HEADER.fullmatch(line)
            if not match or match[1] != match[2]:
                raise ArtifactError("unsupported patch header or rename")
            path = _path(match[1])
            if path in files:
                raise ArtifactError("duplicate patch path")
            files.append(path)
            current = match[1]
            in_body = minus = plus = executable = False
            continue
        if current is None:
            raise ArtifactError("patch has data outside a file section")
        if in_body:
            # Text hunks have a prefix on every data line; Git's binary patch
            # payload consists of base85 lines. A new file header is handled
            # above. Path/mode metadata is never accepted inside a body.
            if line.startswith(
                (
                    b"--- ",
                    b"+++ ",
                    b"old mode ",
                    b"new mode ",
                    b"new file mode ",
                    b"deleted file mode ",
                    b"rename ",
                    b"copy ",
                )
            ):
                raise ArtifactError("unexpected metadata inside patch body")
            continue
        if line.startswith((b"rename ", b"copy ", b"similarity index ", b"dissimilarity index ")):
            raise ArtifactError("renames and copies are not supported")
        if line.startswith((b"old mode ", b"new mode ", b"new file mode ", b"deleted file mode ")):
            mode = line.rsplit(b" ", 1)[-1]
            if mode != b"100644":
                raise ArtifactError("symlinks, executables and submodules are not supported")
        elif line.startswith(b"index "):
            match = re.fullmatch(rb"index [0-9a-f]+\.\.[0-9a-f]+(?: (100644|100755))?", line)
            if not match:
                raise ArtifactError("unsupported index or file mode")
            executable = match[1] == b"100755"
        elif line.startswith(b"--- "):
            if minus or line[4:] not in (b"a/" + current, b"/dev/null"):
                raise ArtifactError("mismatched patch source path")
            if line[4:] == b"/dev/null" and executable:
                raise ArtifactError("new executable files are not supported")
            minus = True
        elif line.startswith(b"+++ "):
            if plus or not minus or line[4:] not in (b"b/" + current, b"/dev/null"):
                raise ArtifactError("mismatched patch destination path")
            plus = True
        elif line.startswith(b"@@ "):
            if not minus or not plus:
                raise ArtifactError("text hunk missing path headers")
            in_body = True
        elif line == b"GIT binary patch":
            if minus or plus:
                raise ArtifactError("unexpected binary patch headers")
            in_body = True
        else:
            raise ArtifactError("unsupported patch metadata")
    return files
