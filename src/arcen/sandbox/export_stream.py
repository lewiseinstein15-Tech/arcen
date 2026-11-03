"""Bounded collection of a fixed container exec stream for A-03.

This is a partial building block: it does not create a baseline, export a diff,
validate a patch, save an artifact, or integrate with a server turn.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from arcen.sandbox.patch_validation import MAX_PATCH_BYTES, ArtifactError


class Killable(Protocol):
    def kill(self) -> object: ...


def collect_export_stream(
    chunks: Iterable[tuple[bytes | None, bytes | None]],
    container: Killable,
    *,
    limit: int = MAX_PATCH_BYTES,
) -> tuple[bytes, bytes]:
    """Collect demultiplexed output without silently truncating either stream.

    The configured maximum is immutable. On an oversize or malformed stream,
    stop the disposable container and raise; no partial bytes are returned.
    The caller remains responsible for closing the stream and container.
    """
    if type(limit) is not int or not 0 < limit <= MAX_PATCH_BYTES:
        raise ValueError("export limit exceeds immutable cap")
    stdout, stderr = bytearray(), bytearray()
    try:
        for item in chunks:
            if not isinstance(item, tuple) or len(item) != 2:
                raise ArtifactError("invalid sandbox export stream")
            out, err = item
            if (out is not None and not isinstance(out, bytes)) or (
                err is not None and not isinstance(err, bytes)
            ):
                raise ArtifactError("invalid sandbox export stream")
            out, err = out or b"", err or b""
            if len(stdout) + len(stderr) + len(out) + len(err) > limit:
                raise ArtifactError(f"sandbox export exceeded {limit} bytes")
            stdout.extend(out)
            stderr.extend(err)
    except Exception as exc:  # Output stream failures must stop the sandbox.
        try:
            container.kill()
        except Exception as kill_exc:
            raise ArtifactError("sandbox export rejected; container stop failed") from kill_exc
        if isinstance(exc, ArtifactError):
            raise
        raise ArtifactError("sandbox export stream failed") from exc
    return bytes(stdout), bytes(stderr)
