"""ARCEN — system info tool (Part 3 wrapped)."""

from __future__ import annotations

import platform
import sys

from pydantic import BaseModel

from .registry import BaseTool


class SystemInfo(BaseTool):
    name = "system.info"
    description = "Python version, platform, and host name of the runner."
    version = "1.0.0"
    danger = "safe"

    class Args(BaseModel):
        pass

    def _run(self, a: "SystemInfo.Args") -> dict:
        return {
            "python": sys.version.split()[0],
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "node": platform.node(),
        }
