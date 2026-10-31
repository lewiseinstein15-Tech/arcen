"""Native reviewed-probe executor seam; not a plugin or trust boundary.

The only wired implementation uses the existing Docker-only probe path. A
structural interface does not certify an executor's isolation or evidence.
External implementations are not selectable by comparisons or portability.
"""

from __future__ import annotations

from typing import Protocol

from arcen.config import ArcenConfig

from .probe_execution import ReviewedProbeResult, _run_bound_probe
from .probe_model import BoundProbeModel
from .probe_workspace import GitSnapshot
from .resolver import HarnessError


class ProbeExecutor(Protocol):
    """Shape for a trusted executor operating on already reviewed inputs.

    Implementations may contact a provider and execute tools. This interface is
    not an authorization or sandbox guarantee; callers must trust the executor.
    """

    def execute(
        self, snapshot: GitSnapshot, config: ArcenConfig, model: BoundProbeModel
    ) -> ReviewedProbeResult: ...


class NativeDockerProbeExecutor:
    """Use ARCEN's existing reviewed Docker path without a host fallback."""

    __slots__ = ()

    def execute(
        self, snapshot: GitSnapshot, config: ArcenConfig, model: BoundProbeModel
    ) -> ReviewedProbeResult:
        if (
            type(snapshot) is not GitSnapshot
            or type(config) is not ArcenConfig
            or type(model) is not BoundProbeModel
        ):
            raise HarnessError("native executor requires reviewed probe inputs")
        if config.sandbox.network != "none" or config.sandbox.backend not in ("auto", "docker"):
            raise HarnessError("native executor requires Docker with networking disabled")
        return _run_bound_probe(snapshot, config, model)
