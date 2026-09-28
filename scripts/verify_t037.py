#!/usr/bin/env python3
"""T-037 live verify — the two verify commands from the ticket, over real HTTP.

Case A (no provider):  unset provider → POST "build a calculator" →
  expect a clean configure-a-provider answer, NO plan, NO command
  events, no "command not found" anywhere on the stream.
Case B (provider):     same message against the mock provider →
  expect a real plan whose steps carry real tool args, a bash run that
  executes the planned command (not the raw goal), and run.done ok.

Boots the mock provider (scripts/mock_provider.py) + uvicorn in
subprocesses, polls the NDJSON stream, prints PASS/FAIL per check.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
MOCK_PORT = 9377
SRV_PORT = 3187
BASE = f"http://127.0.0.1:{SRV_PORT}"
GOAL = "build a calculator"


def wait_healthy(url: str, deadline_s: float = 30.0) -> None:
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        try:
            httpx.get(url, timeout=2.0)  # any HTTP answer (even 501) means up
            return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(f"not healthy in {deadline_s}s: {url}")


def run_turn(goal: str) -> list[dict]:
    session = f"s-t037-{time.time_ns() % 1000000}"
    resp = httpx.post(f"{BASE}/api/run", json={"goal": goal, "session": session}, timeout=10)
    assert resp.status_code == 200, resp.text
    events: list[dict] = []
    with httpx.stream("GET", f"{BASE}/api/stream?session={session}", timeout=30.0) as stream:
        for line in stream.iter_lines():
            if not line.strip():
                continue
            events.append(json.loads(line))
            if events[-1]["type"] in ("run.done", "run.error", "stream.done"):
                break
    return events


def write_provider_config(path: Path) -> None:
    sys.path.insert(0, str(ROOT / "src"))
    from arcen.config import ArcenConfig, save_config

    cfg = ArcenConfig()
    cfg.provider.default = "custom"
    cfg.provider.api_keys = {"custom": "mock-key"}
    cfg.provider.base_urls = {"custom": f"http://127.0.0.1:{MOCK_PORT}/v1"}
    cfg.provider.models = {
        "planner": "mock-model",
        "executor": "mock-model",
        "verifier": "mock-model",
    }
    save_config(path, cfg)


def main() -> int:
    results: list[tuple[bool, str]] = []
    procs: list[subprocess.Popen] = []

    def stop() -> None:
        for p in procs:
            try:
                p.send_signal(signal.SIGTERM)
                p.wait(timeout=5)
            except Exception:
                p.kill()

    try:
        # -- boot the mock provider ------------------------------------------
        mock_log = open("/tmp/t037_mock.log", "w")
        procs.append(
            subprocess.Popen(
                [sys.executable, str(ROOT / "scripts" / "mock_provider.py"), str(MOCK_PORT)],
                stdout=mock_log,
                stderr=mock_log,
            )
        )
        wait_healthy(f"http://127.0.0.1:{MOCK_PORT}/health".replace("/health", "/"), 15)

        # -- Case A: no provider ---------------------------------------------
        no_cfg = Path("/tmp/t037-noprovider/empty.yaml")  # nonexistent → defaults
        env = {**os.environ, "ARCEN_CONFIG_PATH": str(no_cfg)}
        log_a = open("/tmp/t037_srv_a.log", "w")
        procs.append(
            subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "arcen.server.app:app",
                 "--host", "127.0.0.1", "--port", str(SRV_PORT), "--log-level", "error"],
                cwd=str(ROOT), env=env, stdout=log_a, stderr=log_a,
            )
        )
        wait_healthy(f"{BASE}/api/health")

        events = run_turn(GOAL)
        kinds = [e["type"] for e in events]
        answers = [e for e in events if e["type"] == "answer"]
        blob = json.dumps(events)
        results.append((kinds[0] == "run.start", "A: turn starts"))
        results.append(("plan" not in kinds, "A: no plan event (no fake plan)"))
        results.append(("command" not in kinds, "A: no command event (nothing executed)"))
        results.append(("replan" not in kinds, "A: no replan attempts"))
        results.append((bool(answers), "A: an answer reached the stream"))
        results.append((
            bool(answers) and "model provider" in answers[0]["text"]
            and "Settings" in answers[0]["text"],
            "A: answer tells the user to configure a provider in Settings",
        ))
        results.append(("command not found" not in blob, "A: zero 'command not found'"))
        results.append((
            events[-1]["type"] == "run.done" and events[-1]["status"] == "ok",
            "A: run.done ok — a clean turn, not a Turn failed",
        ))

        # stop server A
        procs[-1].send_signal(signal.SIGTERM)
        procs[-1].wait(timeout=5)
        procs.pop()

        # -- Case B: provider configured (mock) ------------------------------
        cfg_path = Path("/tmp/t037-withprovider/config.yaml")
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        write_provider_config(cfg_path)
        env = {**os.environ, "ARCEN_CONFIG_PATH": str(cfg_path)}
        log_b = open("/tmp/t037_srv_b.log", "w")
        procs.append(
            subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "arcen.server.app:app",
                 "--host", "127.0.0.1", "--port", str(SRV_PORT), "--log-level", "error"],
                cwd=str(ROOT), env=env, stdout=log_b, stderr=log_b,
            )
        )
        wait_healthy(f"{BASE}/api/health")

        events = run_turn(GOAL)
        kinds = [e["type"] for e in events]
        plans = [e for e in events if e["type"] == "plan"]
        cmds = [e for e in events if e["type"] == "command"]
        results.append(("plan" in kinds, "B: a real plan is produced"))
        if plans:
            steps = plans[0]["steps"]
            bash = [s for s in steps if s.get("tool") == "bash"]
            results.append((bool(bash), "B: plan has bash steps"))
            results.append((
                all(s.get("args") for s in bash),
                "B: bash steps carry REAL args (the hack is gone)",
            ))
        results.append((bool(cmds), "B: commands executed"))
        if cmds:
            bash_args = next(
                ((c.get("args") or {}) for c in cmds if c.get("tool") == "bash"), {}
            )
            results.append((
                bash_args.get("cmd") == "echo mock-work: build a calculator",
                f"B: the executed cmd comes from the plan, not the goal ({bash_args})",
            ))
        results.append((
            events[-1]["type"] == "run.done" and events[-1]["status"] == "ok",
            "B: run.done ok",
        ))
    finally:
        stop()

    print("\n=== T-037 live verify ===")
    failed = 0
    for ok, label in results:
        print(("  PASS  " if ok else "  FAIL  ") + label)
        failed += 0 if ok else 1
    total = len(results)
    print(f"{total - failed}/{total} checks")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
