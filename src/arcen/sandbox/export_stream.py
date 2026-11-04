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


# A fixed exporter, never generated from workspace data or the model. This runs
# only in the disposable container. The resulting tar is untrusted regardless.
CONTAINER_EXPORTER = r"""
import os
import sys
import tarfile

with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as tar:
    def fail(exc):
        raise exc
    for root, dirs, files in os.walk(".", followlinks=False, onerror=fail):
        dirs[:] = sorted(name for name in dirs if name.lower() != ".git")
        files = sorted(name for name in files if name.lower() != ".git")
        for name in dirs + files:
            path = os.path.join(root, name)
            tar.add(path, arcname=path[2:], recursive=False)
"""


def export_workspace(client, container: Killable) -> bytes:
    """Execute the fixed tar producer in the existing container and cap output.

    Do not use the returned archive without the host-side safe extractor. Failed
    execution, transport errors, oversized output and stderr all reject it.
    """
    api = client.api
    stream = None
    try:
        created = api.exec_create(
            container.id,
            cmd=[
                "timeout",
                "--kill-after=2s",
                "120s",
                "/usr/local/bin/python",
                "-I",
                "-c",
                CONTAINER_EXPORTER,
            ],
            user="65534:65534",
            privileged=False,
            workdir="/workspace",
            environment={"HOME": "/tmp", "LANG": "C.UTF-8", "PATH": "/usr/local/bin:/usr/bin:/bin"},
        )
        exec_id = created["Id"]
        stream = api.exec_start(exec_id, stream=True, demux=True)
        stdout, stderr = collect_export_stream(stream, container)
        if api.exec_inspect(exec_id).get("ExitCode") != 0 or stderr:
            raise ArtifactError("sandbox workspace export failed")
        return stdout
    except ArtifactError:
        raise
    except Exception as exc:
        raise ArtifactError("sandbox workspace export failed") from exc
    finally:
        if stream is not None:
            close = getattr(stream, "close", None)
            if close is not None:
                close()
