"""Exact known-value screening for bounded probe snapshots; not a secret scanner."""

from __future__ import annotations

from arcen.sandbox.workspace import MAX_BYTES

from .probe import ProbeUnavailable
from .probe_workspace import _MAX_TAR_OVERHEAD, GitSnapshot


class SensitiveSnapshot(ProbeUnavailable):
    """A known secret was found in the reviewed workspace snapshot."""


def _reject_snapshot_secrets(snapshot: GitSnapshot, known_values: tuple[str, ...]) -> None:
    """Reject exact known secret bytes without logging or disclosing a match.

    The immutable tar bytes are searched before a trial is admitted or a
    container is created. This is not a general secret scanner and does not
    detect encoded, transformed, split, or unknown credentials.
    """
    if (
        type(snapshot) is not GitSnapshot
        or type(snapshot.archive) is not bytes
        or len(snapshot.archive) > MAX_BYTES + _MAX_TAR_OVERHEAD
    ):
        raise ProbeUnavailable("invalid probe workspace snapshot")
    if type(known_values) is not tuple or len(known_values) > 32:
        raise ProbeUnavailable("invalid known-secret configuration")
    for value in known_values:
        if type(value) is not str or not 4 <= len(value) <= 256:
            raise ProbeUnavailable("invalid known-secret configuration")
        try:
            encoded = value.encode("utf-8")
        except UnicodeError:
            raise ProbeUnavailable("invalid known-secret configuration") from None
        if encoded in snapshot.archive:
            raise SensitiveSnapshot(
                "reviewed workspace contains a known sensitive value; no probe was started"
            )
