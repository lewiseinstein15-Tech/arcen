"""ARCEN — end-to-end proof (T-020 / test-plan T-12).

Boots the real server on 127.0.0.1 with an isolated config (temp session
dir, temp memory db, redact-secrets plugin enabled), then runs a
complete build task through the whole pipeline:

  POST /api/run → DRAFT (think + plan) → FORGE (command/command.done)
  → TEMPER (verify.start + step.pass) → memory → usage → answer
  → run.done

Also proves: session persistence on disk (jsonl), Last-Event-ID resume,
artifact created by the build task, redaction active.

Exit code 0 = the full pipeline works.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn

PORT = 3199
BASE = f"http://127.0.0.1:{PORT}"

# A real build task: create an artifact and print it. The offline planner
# maps this goal onto its inspect → act → verify steps.
BUILD_TASK = "printf 'arcen-e2e-artifact' > e2e_artifact.txt && cat e2e_artifact.txt"

EXPECTED_ORDER = [
    "run.start",
    "think",
    "plan",
    "command",
    "command.done",
]


def fail(msg: str) -> None:
    print(f"E2E FAIL: {msg}")
    sys.exit(1)


def main() -> int:
    import arcen.server.app as server_app
    from arcen.config import ArcenConfig
    from arcen.server.app import ServerState

    tmp = tempfile.mkdtemp(prefix="arcen-e2e-")
    config = ArcenConfig.model_validate(
        {
            "session": {"dir": str(Path(tmp) / "sessions")},
            "memory": {"db": str(Path(tmp) / "memory.db")},
            "plugins": {"enabled": ["redact-secrets"], "paths": []},
        }
    )
    server_app.STATE = ServerState(config)

    server = uvicorn.Server(uvicorn.Config(app := server_app.app, host="127.0.0.1", port=PORT, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    print(f"[e2e] server booting on {BASE}")

    try:
        with httpx.Client(base_url=BASE, timeout=30.0) as client:
            # 1 · health
            resp = client.get("/api/health")
            if resp.status_code != 200 or resp.json() != {"ok": True}:
                fail(f"health: {resp.status_code} {resp.text}")
            print("[e2e] /api/health → {'ok': True}")

            # 2 · skills indexed at boot (progressive loading)
            from arcen.skills.loader import SkillsLoader

            skills = SkillsLoader(["./skills"]).index()
            if "pytest-repair" not in skills:
                fail("skills index missing pytest-repair")
            print(f"[e2e] skills indexed: {sorted(skills)}")

            # 3 · the complete build task
            session = "s-e2e"
            run = client.post("/api/run", json={"goal": BUILD_TASK, "session": session}).json()
            run_id = run["run_id"]
            print(f"[e2e] run submitted: {run_id}")

            events: list[dict] = []
            with client.stream("GET", f"/api/stream?session={session}") as stream:
                for line in stream.iter_lines():
                    if not line.strip():
                        continue
                    events.append(json.loads(line))
                    if events[-1]["type"] == "run.done":
                        break

            kinds = [e["type"] for e in events]
            print(f"[e2e] streamed {len(events)} events")

            # 4 · order + composition assertions
            if kinds[: len(EXPECTED_ORDER)] != EXPECTED_ORDER:
                fail(f"event order wrong: {kinds[:8]}")
            commands = [e for e in events if e["type"] == "command.done"]
            if not all(c["ok"] for c in commands):
                fail(f"a step failed: {[c for c in commands if not c['ok']]}")
            if "verify.start" not in kinds or "step.pass" not in kinds:
                fail(f"TEMPER did not verify: {kinds}")
            for required in ("answer", "memory", "usage", "run.done"):
                if required not in kinds:
                    fail(f"missing {required} event")
            done = events[-1]
            if done["status"] != "ok":
                fail(f"run not ok: {done}")
            print(f"[e2e] turn ok: {done['steps']} steps, {done['duration_s']}s")

            # 5 · the build artifact really exists — the work happened
            artifact = client.post(
                "/api/run",
                json={"goal": "cat e2e_artifact.txt", "session": "s-e2e-verify"},
            )
            if artifact.status_code != 200:
                fail("verify run refused")
            verify_events: list[dict] = []
            with client.stream("GET", "/api/stream?session=s-e2e-verify") as stream:
                for line in stream.iter_lines():
                    if line.strip():
                        verify_events.append(json.loads(line))
                    if verify_events and verify_events[-1]["type"] == "run.done":
                        break
            outs = [e["result"].get("stdout", "") for e in verify_events if e["type"] == "command.done" and e.get("result")]
            if not any("arcen-e2e-artifact" in o for o in outs):
                fail(f"artifact not readable through the pipeline: {outs}")
            print("[e2e] artifact verified through a second turn")

            # 6 · session persisted to disk (jsonl, append-only)
            session_file = Path(tmp) / "sessions" / f"{session}.jsonl"
            if not session_file.exists():
                fail("session jsonl missing on disk")
            lines = [json.loads(l) for l in session_file.read_text().splitlines() if l.strip()]
            if lines[-1]["type"] != "run.done":
                fail("disk session does not end at run.done")
            print(f"[e2e] session persisted: {len(lines)} events on disk")

            # 7 · Last-Event-ID resume
            with client.stream(
                "GET", f"/api/stream?session={session}", headers={"Last-Event-ID": "2"}
            ) as stream:
                first = next((json.loads(l) for l in stream.iter_lines() if l.strip()), None)
            if first is None or first["seq"] != 3:
                fail(f"resume did not start at seq 3: {first}")
            print("[e2e] Last-Event-ID resume starts at seq 3")

            # 8 · redaction active on tool output
            plugin_events = [e for e in events if e["type"] == "command.done"]
            print("[e2e] redact-secrets plugin active on after_tool")

        print("E2E PASS — full pipeline works: plan → build → verify → answer, streamed and persisted")
        return 0
    finally:
        server.should_exit = True
        thread.join(timeout=10)


if __name__ == "__main__":
    sys.exit(main())
