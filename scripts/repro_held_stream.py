#!/usr/bin/env python3
"""Repro: held stream + live delivery. Reader thread prints every line;
poster thread runs the turn; main asserts stream.done within 10s."""

import json
import sys
import threading
import time
import uuid

sys.path.insert(0, "/home/z/arcen")
sys.path.insert(0, "/home/z/arcen/tests")

import httpx
import uvicorn

import arcen.server.app as server_app
from arcen.config import ArcenConfig
from arcen.llm.client import LLMResponse
from arcen.server.app import ServerState, app

PORT = 3199
BASE = f"http://127.0.0.1:{PORT}"


class Stub:
    def is_available(self):
        return True

    def complete(self, role, messages, **kwargs):
        content = messages[-1]["content"]
        if "Return ONLY the word" in content:
            return LLMResponse(text="CODE", model="stub", tokens={"input": 1, "output": 1})
        goal_line = next((ln for ln in content.splitlines() if ln.startswith("Goal: ")), "")
        goal = goal_line[len("Goal: "):].strip() or "true"
        plan = json.dumps([
            {"title": f"run: {goal[:40]}", "tool": "bash", "args": {"cmd": goal}},
            {"title": "checkpoint", "tool": "bash", "args": {"cmd": "true"}},
        ])
        return LLMResponse(text=plan, model="stub", tokens={"input": 8, "output": 8})


server_app.STATE = ServerState(config=ArcenConfig())
server_app.STATE.config_path = server_app.default_config_path().parent / "config.yaml.test"
server_app.STATE.llm = Stub()

server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error"))
thread = threading.Thread(target=server.run, daemon=True)
thread.start()
while not server.started:
    time.sleep(0.05)

session = str(uuid.uuid4())
lines: list[str] = []
reader_err: list[str] = []


def reader():
    try:
        with httpx.Client(base_url=BASE, timeout=httpx.Timeout(30.0, read=8.0)) as c:
            with c.stream("GET", f"/api/stream?session={session}") as resp:
                print(f"[reader] status={resp.status_code}", flush=True)
                for line in resp.iter_lines():
                    print(f"[reader] line: {line[:110]}", flush=True)
                    lines.append(line)
                    if '"stream.done"' in line:
                        return
    except Exception as exc:  # noqa: BLE001
        reader_err.append(repr(exc))
        print(f"[reader] EXC {exc!r}", flush=True)


rt = threading.Thread(target=reader, daemon=True)
rt.start()
time.sleep(1.0)  # reader attached

t0 = time.time()
with httpx.Client(base_url=BASE, timeout=10.0) as c:
    r = c.post("/api/run", json={"goal": "echo held-live", "session": session})
    print(f"[poster] POST /api/run -> {r.status_code} {r.text[:80]}", flush=True)

rt.join(timeout=12)
print(f"\n[main] reader alive after join: {rt.is_alive()}; lines={len(lines)}; err={reader_err}")
for ln in lines:
    try:
        w = json.loads(ln)
        print(f"  seq={w.get('seq')} type={w.get('type')}")
    except Exception:
        print(f"  RAW {ln[:80]}")
server.should_exit = True
thread.join(timeout=5)
sys.exit(0 if any('"stream.done"' in ln for ln in lines) else 1)
