"""ARCEN — live-streaming fix verification (ticket: FIX LIVE STREAMING).

Boots the REAL stack in one process (uvicorn + vite + chromium) and proves:

  V1  "hello" reply appears live WITHOUT any page refresh
  V2  "what is 2+2?" reply appears live WITHOUT refresh
  V3  three consecutive turns — every reply visible, no refresh
  V4  server access log: GET /api/stream → 200 per turn, ZERO 400s
  V5  the laptop scenario: backend restart + stale Last-Event-ID → 200 replay

Screenshots land in /home/z/my-project/download/screenshots/ (before any
reload is ever performed).
"""

import json
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx
import uvicorn
from playwright.sync_api import sync_playwright

import arcen.server.app as server_app
from arcen.server.app import ServerState, app

PORT = 3002
BASE = f"http://127.0.0.1:{PORT}"
UI_PORT = 5173
UI = f"http://localhost:{UI_PORT}"
SHOTS = Path("/home/z/my-project/download/screenshots")
SHOTS.mkdir(parents=True, exist_ok=True)

# --- capture the uvicorn ACCESS log (the ticket's P5 evidence) ----------------
access_lines: list[str] = []


class AccessCapture(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        access_lines.append(record.getMessage())


logging.getLogger("uvicorn.access").addHandler(AccessCapture())
logging.getLogger("uvicorn.access").setLevel(logging.INFO)

REPORT: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    line = f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else "")
    REPORT.append(line)
    print(line, flush=True)
    return ok


def wait_health(client: httpx.Client, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if client.get(f"{BASE}/api/health").status_code == 200:
                return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("backend never became healthy")


def stream_until(client: httpx.Client, session: str, want: str = "run.done",
                 last_event_id: int | None = None, limit: int = 400) -> list[dict]:
    headers = {"Last-Event-ID": str(last_event_id)} if last_event_id is not None else {}
    events: list[dict] = []
    with client.stream("GET", f"{BASE}/api/stream?session={session}", headers=headers) as resp:
        assert resp.status_code == 200, f"stream status {resp.status_code}"
        for line in resp.iter_lines():
            if not line.strip():
                continue
            events.append(json.loads(line))
            if events[-1]["type"] in (want, "stream.done") or len(events) >= limit:
                break
    return events


def main() -> int:
    # ---- boot the real backend (same object graph as dev.sh) -----------------
    server_app.STATE = ServerState()
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="info", log_config=None)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    vite = None
    browser = None
    ok = True
    try:
        with httpx.Client(base_url=BASE, timeout=30.0) as client:
            wait_health(client)

            # ---- V0: API-level hello — one stream, 200, sentinel, clean close
            client.post("/api/run", json={"goal": "hello", "session": "s-api"})
            t0 = time.time()
            events = stream_until(client, "s-api")
            dt = time.time() - t0
            kinds = [e["type"] for e in events]
            check("V0 hello turn: single stream 200 + run.done + clean close",
                  "run.done" in kinds and kinds[-1] in ("run.done", "stream.done") and dt < 10,
                  f"{len(events)} events in {dt:.2f}s, last={kinds[-1]}")

            # ---- boot vite (real UI, real proxy) --------------------------------
            vite = subprocess.Popen(
                ["npm", "run", "dev"], cwd="/home/z/arcen/ui",
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            ui_up = False
            for _ in range(60):
                try:
                    if httpx.get(UI, timeout=2.0).status_code == 200:
                        ui_up = True
                        break
                except Exception:
                    time.sleep(0.5)
            check("vite dev server up on :5173", ui_up)

            # ---- browser: drive the REAL UI ------------------------------------
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                stream_reqs: list[str] = []  # client-side /api/stream requests
                stream_statuses: list[int] = []

                def on_request(req):
                    if "/api/stream" in req.url:
                        stream_reqs.append(req.url)

                def on_response(resp):
                    if "/api/stream" in resp.url:
                        stream_statuses.append(resp.status)

                page.on("request", on_request)
                page.on("response", on_response)

                page.goto(UI, wait_until="domcontentloaded")
                page.wait_for_selector('[data-testid="composer-input"]')

                def bot_messages() -> int:
                    return page.locator(".bot-message").count()

                def send(text: str) -> None:
                    page.fill('[data-testid="composer-input"]', text)
                    page.click('[data-testid="send-btn"]')

                # V1 — hello, live, no refresh
                before = bot_messages()
                send("hello")
                page.wait_for_selector(".bot-message", timeout=15000)
                page.wait_for_function(
                    f"document.querySelectorAll('.bot-message').length > {before}",
                    timeout=15000,
                )
                live_text = page.inner_text('[data-testid="stream"]')
                check("V1 hello reply visible WITHOUT refresh",
                      "DRAFT plans, FORGE executes" in live_text)
                page.screenshot(path=str(SHOTS / "07-hello-live.png"))
                print(f"      screenshot → {SHOTS / '07-hello-live.png'}", flush=True)

                # V2 — what is 2+2? live, no refresh
                before = bot_messages()
                send("what is 2+2?")
                page.wait_for_function(
                    f"document.querySelectorAll('.bot-message').length > {before}",
                    timeout=20000,
                )
                check("V2 'what is 2+2?' reply visible WITHOUT refresh", True)
                page.screenshot(path=str(SHOTS / "08-2plus2-live.png"))
                print(f"      screenshot → {SHOTS / '08-2plus2-live.png'}", flush=True)

                # V3 — three consecutive turns, no refresh
                for i, goal in enumerate(["list the files here", "echo turn-three", "final check"], 1):
                    before = bot_messages()
                    send(goal)
                    page.wait_for_function(
                        f"document.querySelectorAll('.bot-message').length > {before}",
                        timeout=25000,
                    )
                    check(f"V3.{i} turn '{goal}' streamed live (no refresh)", True)

                page.screenshot(path=str(SHOTS / "09-three-turns-live.png"))
                print(f"      screenshot → {SHOTS / '09-three-turns-live.png'}", flush=True)

                # V4 — client-side: every stream response was a 200
                bad = [s for s in stream_statuses if s != 200]
                check("V4 UI-side: all /api/stream responses were 200",
                      len(stream_statuses) > 0 and not bad,
                      f"{len(stream_reqs)} requests, statuses={sorted(set(stream_statuses))}, non-200={bad}")

                browser.close()
                browser = None  # the context manager owns teardown now

            # ---- server-side access log: zero 400s on /api/stream --------------
            time.sleep(1.0)
            stream_access = [l for l in access_lines if "/api/stream" in l]
            err400 = [l for l in stream_access if " 400 " in l]
            run_access = [l for l in access_lines if "POST /api/run" in l]
            check("V4 server log: zero 400s on /api/stream",
                  len(stream_access) > 0 and not err400,
                  f"{len(stream_access)} stream GETs, {len(err400)} x 400, {len(run_access)} runs")
            check("V4 server log: one stream attach per turn (no retry storm)",
                  len(stream_access) <= len(run_access) + 1,
                  f"{len(stream_access)} GETs vs {len(run_access)} turns (<= turns+1)")

        # ---- V5: the laptop scenario — restart + stale Last-Event-ID ----------
        with httpx.Client(base_url=BASE, timeout=30.0) as client:
            wait_health(client)
            client.post("/api/run", json={"goal": "echo restart-proof", "session": "s-restart"})
            events = stream_until(client, "s-restart")
            last_seq = events[-1]["seq"]
            stale_id = last_seq + 50  # what the laptop's localStorage had

            server_app.STATE = ServerState()  # 💥 process restart: memory wiped
            assert "s-restart" not in server_app.STATE.emitters

            resp = client.get(f"{BASE}/api/stream?session=s-restart",
                              headers={"Last-Event-ID": str(stale_id)})
            lines = [json.loads(l) for l in resp.text.splitlines() if l.strip()]
            check("V5 restart + stale Last-Event-ID → 200 full replay (was 400 loop)",
                  resp.status_code == 200
                  and lines[0]["seq"] == 1
                  and lines[-1]["type"] == "stream.done",
                  f"status={resp.status_code}, first_seq={lines[0]['seq']}, last={lines[-1]['type']}")

            client.post("/api/run", json={"goal": "echo after-restart", "session": "s-restart"})
            resumed = stream_until(client, "s-restart", last_event_id=last_seq)
            check("V5 seq continuity after restart (new turn continues at N+1)",
                  resumed[0]["seq"] == last_seq + 1,
                  f"disk tail={last_seq}, first new seq={resumed[0]['seq']}")

    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if vite is not None:
            vite.terminate()
            try:
                vite.wait(timeout=5)
            except subprocess.TimeoutExpired:
                vite.kill()
        server.should_exit = True
        thread.join(timeout=10)

    log_path = Path("/tmp/arcen_access.log")
    log_path.write_text("\n".join(access_lines))
    print(f"\n--- uvicorn access log → {log_path} ---", flush=True)
    for line in access_lines:
        if "/api/" in line:
            print("   " + line, flush=True)
    fails = sum(1 for r in REPORT if r.startswith("FAIL"))
    print(f"\n===== {len(REPORT) - fails}/{len(REPORT)} checks passed =====", flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    import threading

    sys.exit(main())
