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
    index_seen = minus = plus = False
    mode_kind: bytes | None = None
    executable = False
    old_zero = new_zero = False
    body: str | None = None
    old_left = new_left = 0
    last_content = False
    binary_blocks = 0
    binary_lines = 0
    binary_open = False

    def finish() -> None:
        if current is None:
            return
        if not index_seen:
            raise ArtifactError("patch section missing index")
        if body == "text" and (old_left or new_left):
            raise ArtifactError("truncated text hunk")
        if body == "binary" and (binary_open or binary_blocks == 0):
            raise ArtifactError("truncated binary patch")
        if body is None and (mode_kind is None or minus or plus):
            raise ArtifactError("patch section has no content or has incomplete headers")
        if mode_kind == b"new" and (not old_zero or new_zero or executable):
            raise ArtifactError("invalid new file metadata")
        if mode_kind == b"deleted" and (not new_zero or old_zero or executable):
            raise ArtifactError("invalid deleted file metadata")
        if mode_kind is None and (old_zero or new_zero):
            raise ArtifactError("file creation or deletion missing mode")

    def hunk(line: bytes) -> tuple[int, int]:
        match = re.fullmatch(rb"@@ -[0-9]+(?:,([0-9]+))? \+[0-9]+(?:,([0-9]+))? @@(?: .*)?", line)
        if not match:
            raise ArtifactError("invalid text hunk header")
        counts = (match[1] or b"1", match[2] or b"1")
        if any(len(count) > 8 or int(count) > MAX_PATCH_BYTES for count in counts):
            raise ArtifactError("text hunk exceeds size limit")
        return int(counts[0]), int(counts[1])

    # Git's base85 alphabet has no whitespace; the first letter encodes length.
    binary_data = re.compile(rb"[A-Za-z][0-9A-Za-z!#$%&()*+;<=>?@^_`{|}~-]+\Z")
    for line in patch[:-1].split(b"\n"):
        if line.startswith(b"diff --git "):
            finish()
            match = _HEADER.fullmatch(line)
            if not match or match[1] != match[2]:
                raise ArtifactError("unsupported patch header or rename")
            path = _path(match[1])
            if path in files:
                raise ArtifactError("duplicate patch path")
            files.append(path)
            current = match[1]
            index_seen = minus = plus = executable = old_zero = new_zero = False
            mode_kind = body = None
            old_left = new_left = binary_blocks = binary_lines = 0
            last_content = binary_open = False
            continue
        if current is None:
            raise ArtifactError("patch has data outside a file section")
        if body == "text":
            if line.startswith(b"@@ "):
                if old_left or new_left:
                    raise ArtifactError("truncated text hunk")
                old_left, new_left = hunk(line)
                last_content = False
            elif line == b"\\ No newline at end of file":
                if not last_content:
                    raise ArtifactError("unexpected no-newline marker")
                last_content = False
            elif line[:1] in (b" ", b"+", b"-") and (old_left or new_left):
                if line[:1] in (b" ", b"-"):
                    old_left -= 1
                if line[:1] in (b" ", b"+"):
                    new_left -= 1
                if old_left < 0 or new_left < 0:
                    raise ArtifactError("text hunk length mismatch")
                last_content = True
            else:
                raise ArtifactError("unexpected metadata inside patch body")
            continue
        if body == "binary":
            if not binary_open:
                if not re.fullmatch(rb"(?:literal|delta) [0-9]+", line) or binary_blocks >= 2:
                    raise ArtifactError("invalid binary patch header")
                size = line.split(b" ")[1]
                if len(size) > 8 or int(size) > MAX_PATCH_BYTES:
                    raise ArtifactError("binary patch exceeds size limit")
                binary_open, binary_lines = True, 0
            elif not line:
                if not binary_lines:
                    raise ArtifactError("empty binary patch block")
                binary_blocks += 1
                binary_open = False
            else:
                if not binary_data.fullmatch(line):
                    raise ArtifactError("invalid binary patch data")
                n = line[0] - 64 if 65 <= line[0] <= 90 else line[0] - 70
                if not 1 <= n <= 52 or len(line) != 1 + 5 * ((n + 3) // 4):
                    raise ArtifactError("invalid binary patch data length")
                binary_lines += 1
            continue
        if line.startswith((b"rename ", b"copy ", b"similarity index ", b"dissimilarity index ")):
            raise ArtifactError("renames and copies are not supported")
        if line.startswith((b"old mode ", b"new mode ")):
            raise ArtifactError("file mode changes are not supported")
        if line.startswith((b"new file mode ", b"deleted file mode ")):
            if mode_kind is not None or index_seen or line.rsplit(b" ", 1)[-1] != b"100644":
                raise ArtifactError("symlinks, executables and submodules are not supported")
            mode_kind = b"new" if line.startswith(b"new ") else b"deleted"
        elif line.startswith(b"index "):
            match = re.fullmatch(rb"index ([0-9a-f]+)\.\.([0-9a-f]+)(?: (100644|100755))?", line)
            if not match or index_seen:
                raise ArtifactError("unsupported index or file mode")
            if (mode_kind is None) != (match[3] is not None):
                raise ArtifactError("missing or inconsistent index file mode")
            index_seen = True
            old_zero = not match[1].strip(b"0")
            new_zero = not match[2].strip(b"0")
            executable = match[3] == b"100755"
        elif line.startswith(b"--- "):
            if not index_seen or minus or line[4:] not in (b"a/" + current, b"/dev/null"):
                raise ArtifactError("mismatched patch source path")
            if (line[4:] == b"/dev/null") != (mode_kind == b"new"):
                raise ArtifactError("mismatched new file metadata")
            minus = True
        elif line.startswith(b"+++ "):
            if plus or not minus or line[4:] not in (b"b/" + current, b"/dev/null"):
                raise ArtifactError("mismatched patch destination path")
            if (line[4:] == b"/dev/null") != (mode_kind == b"deleted"):
                raise ArtifactError("mismatched deleted file metadata")
            plus = True
        elif line.startswith(b"@@ "):
            if not minus or not plus:
                raise ArtifactError("text hunk missing path headers")
            old_left, new_left = hunk(line)
            body = "text"
        elif line == b"GIT binary patch":
            if not index_seen or minus or plus:
                raise ArtifactError("unexpected binary patch headers")
            body = "binary"
        else:
            raise ArtifactError("unsupported patch metadata")
    finish()
    return files
