"""ARCEN — process/environment tools (Part 3 wrapped)."""

from __future__ import annotations

import os
import platform
import time
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from .registry import BaseTool


class ProcEnv(BaseTool):
    name = "proc.env"
    description = "Read an environment variable by name. Reports whether it is set."
    version = "1.0.0"
    danger = "sandboxed"

    class Args(BaseModel):
        name: str = Field(description="environment variable name")

    def _run(self, a: "ProcEnv.Args") -> dict:
        value = os.environ.get(a.name)
        return {"name": a.name, "set": value is not None, "value": value}


class ProcCwd(BaseTool):
    name = "proc.cwd"
    description = "Current working directory of the tool runner."
    version = "1.0.0"
    danger = "safe"

    class Args(BaseModel):
        pass

    def _run(self, a: "ProcCwd.Args") -> dict:
        return {"cwd": os.getcwd()}


class ProcTime(BaseTool):
    name = "proc.time"
    description = "Current Unix epoch seconds and ISO-8601 UTC timestamp."
    version = "1.0.0"
    danger = "safe"

    class Args(BaseModel):
        pass

    def _run(self, a: "ProcTime.Args") -> dict:
        now = time.time()
        return {"epoch": now, "iso": datetime.now(UTC).isoformat()}
