#!/usr/bin/env python3
"""T-038 live verify — the ticket's verify matrix, minus a real docker
daemon (this host has none; that exact case is the clean-error check).

1. backend=process  → a real run executes in the quarantined process
   backend (log confirms backend=process (forced))
2. backend=docker, no daemon → SandboxBackendError with a clear message —
   NO silent fallback
3. boot with sandbox.backend=docker → uvicorn logs the boot warning
4. GET /api/sandbox/status → {docker_available, image_present, image}
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arcen.config import ArcenConfig, save_config  # noqa: E402
from arcen.sandbox.runtime import SandboxBackendError, SandboxRuntime, docker_status  # noqa: E402

PORT = 3188
BASE = f"http://127.0.0.1:{PORT}"
results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((ok, label))


# 1. backend=process → process mode, real run inside the quarantine root
logging.basicConfig(level=logging.INFO, format="%(message)s")
records: list[logging.LogRecord] = []
logging.getLogger().addHandler(lambda: None) if False else None


class _Capture(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        records.append(record)


logging.getLogger("arcen.sandbox").addHandler(_Capture())
logging.getLogger("arcen.sandbox").setLevel(logging.INFO)

rt = SandboxRuntime(config={"sandbox": {"backend": "process"}})
out = rt.run("echo t038-process && pwd")
log_text = "\n".join(r.getMessage() for r in records)
check(rt.backend == "process", "backend=process → runtime.backend == process")
check(out["ok"] is True, "backend=process → a real command runs ok")
check("backend=process (forced)" in log_text, "backend=process → the log confirms the forced backend")
check(
    str(Path(rt.root).name).startswith("arcen-"),
    "backend=process → runs in the unique quarantine root",
)
rt.destroy()

# 2. backend=docker, no daemon → clean error, no silent fallback
try:
    SandboxRuntime(backend="docker")
    check(False, "backend=docker without docker → raises SandboxBackendError")
except SandboxBackendError as exc:
    check(
        "no docker daemon" in str(exc) and "sandbox.backend" in str(exc),
        "backend=docker without docker → clear error naming the fix",
    )
except Exception as exc:  # noqa: BLE001
    check(False, f"backend=docker without docker → wrong error type: {exc}")

# 3. boot the server with sandbox.backend=docker → boot warning in the log
cfg = ArcenConfig()
cfg.sandbox.backend = "docker"
cfg.stream.port = PORT
cfg_path = Path("/tmp/t038-docker/config.yaml")
cfg_path.parent.mkdir(parents=True, exist_ok=True)
save_config(cfg_path, cfg)

# a docker-free host is the norm here — docker_status proves it
status = docker_status(cfg.sandbox.image)
check(
    status["docker_available"] is False and status["image_present"] is False,
    "docker_status reports docker absent (the Settings warning data)",
)

srv_log = open("/tmp/t038_srv.log", "w")  # noqa: SIM115
proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "arcen.server.app:app",
     "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
    cwd=str(ROOT), env={"PATH": "/usr/bin:/bin", "ARCEN_CONFIG_PATH": str(cfg_path)},
    stdout=srv_log, stderr=srv_log,
)
try:
    deadline = time.time() + 25
    up = False
    while time.time() < deadline:
        try:
            if httpx.get(f"{BASE}/api/health", timeout=2.0).status_code == 200:
                up = True
                break
        except Exception:
            time.sleep(0.2)
    check(up, "server boots with backend=docker despite no daemon (Part 10)")

    remote = httpx.get(f"{BASE}/api/sandbox/status", timeout=5).json()
    check(
        set(remote) == {"docker_available", "image_present", "image"},
        "GET /api/sandbox/status returns the three fields",
    )
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    srv_log.close()

boot_log = Path("/tmp/t038_srv.log").read_text()
check(
    "sandbox.backend='docker'" in boot_log and ("no docker daemon" in boot_log or "not present" in boot_log),
    "the boot log carries the docker-pinned warning",
)

print("\n=== T-038 live verify ===")
failed = 0
for ok, label in results:
    print(("  PASS  " if ok else "  FAIL  ") + label)
    failed += 0 if ok else 1
print(f"{len(results) - failed}/{len(results)} checks")
raise SystemExit(1 if failed else 0)
