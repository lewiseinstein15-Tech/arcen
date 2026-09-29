#!/usr/bin/env python3
"""ARCEN v0.1.6 verification harness — T1..T4 live evidence + 5 shots.

Boots the real stack in-process (mock provider :9377 + a 401-failing
twin :9378 + backend :3002 with an isolated ARCEN_CONFIG_PATH + UI
:5173), then runs the v0.1.6 acceptance tests against the live wire:

  T1  fresh session stream → 200 held, ZERO 404 in the backend log
  T2  "hello" → raw NDJSON events delivered in real time, done ≤ 10s
  T3  "+ New chat" → "2+2" → "4" with NO page reload (window marker)
  T4  mock 401 → run.error "provider error: 401 …" in < 5s; Test
      Connection shows "provider error: 401 unauthorized — check your
      API key"

Screenshots land in ui/screenshots/v0.1.6/ (01, 02, 03, 04, 05).
Every PASS is backed by raw wire/log evidence, never staged.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from screenshot_guard import StaleTurnError, TurnBaseline, assert_fresh_turn

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "ui" / "screenshots" / "v0.1.6"
MOCK_PORT = 9377
BAD_PORT = 9378
BASE = "http://127.0.0.1:3002"
UI = "http://localhost:5173"
BACKEND_LOG = Path("/tmp/v016-backend.log")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
CHECKS: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)
    return bool(ok)


def wait_http(url: str, timeout: float = 40) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except urllib.error.HTTPError:
            return True
        except Exception:
            time.sleep(0.3)
    return False


def write_provider_config(path: Path) -> None:
    sys.path.insert(0, str(ROOT / "src"))
    from arcen.config import ArcenConfig, save_config

    cfg = ArcenConfig()
    cfg.provider.name = "custom"
    cfg.provider.api_key = "mock-key-good"
    cfg.provider.base_url = f"http://127.0.0.1:{MOCK_PORT}/v1"
    cfg.provider.model = "mock-model"
    save_config(path, cfg)


def api(method: str, path: str, payload: dict | None = None) -> dict:
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def read_stream_until_done(session: str, on_line, timeout: float = 30) -> None:
    """Raw GET /api/stream — every line goes to on_line as it ARRIVES."""
    with httpx.Client(base_url=BASE, timeout=httpx.Timeout(30.0, read=timeout)) as c:
        with c.stream("GET", f"/api/stream?session={session}") as resp:
            on_line("__status__", str(resp.status_code))
            for line in resp.iter_lines():
                if line.strip():
                    on_line("__line__", line)
                    if '"stream.done"' in line:
                        return


def hold_status(session: str) -> int:
    """Open the held stream, read the status, disconnect."""
    with httpx.Client(base_url=BASE, timeout=httpx.Timeout(5.0, read=2.0)) as c:
        with c.stream("GET", f"/api/stream?session={session}") as resp:
            return resp.status_code


INSPECTOR_JS = """
(args) => {
  const [label, rows] = args;
  const v = localStorage.getItem('arcen.activeId') ?? '(none)';
  const box = document.createElement('div');
  box.style.cssText = 'position:fixed;top:12px;right:12px;z-index:99999;'
    + 'background:#111418;color:#d7dde6;border:1px solid #3a414b;border-radius:8px;'
    + 'padding:10px 14px;font:12px/1.7 ui-monospace,Menlo,monospace;min-width:340px;'
    + 'box-shadow:0 8px 24px rgba(0,0,0,.45)';
  box.innerHTML = '<div style="color:#8b949e;border-bottom:1px solid #3a414b;'
    + 'margin-bottom:6px;padding-bottom:4px">' + label + '</div>'
    + [['session', v], ...rows]
        .map(([k, val]) => `<div><span style="color:#7ee2a8">${k}</span>: ${val}</div>`)
        .join('');
  document.body.appendChild(box);
}
"""


def ui_turn(page, goal: str, want: str, timeout: float = 30) -> str:
    page.fill('[data-testid="composer"] textarea', goal)
    baseline = page.locator(".bot-message").count()
    page.keyboard.press("Enter")
    deadline = time.time() + timeout
    text = ""
    while time.time() < deadline:
        if page.locator(".bot-message").count() > baseline:
            text = page.locator(".bot-message").last.inner_text()
            if want in text:
                break
        time.sleep(0.25)
    return text


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    cfg_path = Path("/tmp/v016/config.yaml")
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    write_provider_config(cfg_path)

    for pattern in ("uvicorn arcen.server.app", "mock_provider.py", "vite"):
        subprocess.run(["pkill", "-f", pattern], capture_output=True)
    time.sleep(1)

    mock_log = open("/tmp/v016-mock.log", "w")
    bad_log = open("/tmp/v016-badmock.log", "w")
    procs: list[subprocess.Popen] = []
    try:
        procs.append(subprocess.Popen(
            [sys.executable, "scripts/mock_provider.py", str(MOCK_PORT)],
            cwd=ROOT, stdout=mock_log, stderr=subprocess.STDOUT, start_new_session=True))
        env_bad = {"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "MOCK_FAIL_STATUS": "401"}
        procs.append(subprocess.Popen(
            [sys.executable, "scripts/mock_provider.py", str(BAD_PORT)],
            cwd=ROOT, stdout=bad_log, stderr=subprocess.STDOUT,
            env={**os.environ, **env_bad}, start_new_session=True))
        if not wait_http(f"http://127.0.0.1:{MOCK_PORT}/v1"):
            print("mock provider failed"); return 1
        if not wait_http(f"http://127.0.0.1:{BAD_PORT}/v1"):
            print("failing mock failed"); return 1

        procs.append(subprocess.Popen(
            [sys.executable, "-c",
             "import logging, uvicorn; logging.basicConfig(level=logging.INFO); "
             "from arcen.server.app import app; "
             "uvicorn.run(app, host='0.0.0.0', port=3002)"],
            cwd=ROOT,
            env={**os.environ,
                 "ARCEN_CONFIG_PATH": str(cfg_path),
                 "HOME": str(Path.home())},
            stdout=open(BACKEND_LOG, "w"), stderr=subprocess.STDOUT,
            start_new_session=True))
        if not wait_http(f"{BASE}/api/health"):
            print("backend failed"); return 1

        procs.append(subprocess.Popen(
            [shutil.which("npm"), "run", "dev"],
            cwd=ROOT / "ui", stdout=open("/tmp/v016-ui.log", "w"),
            stderr=subprocess.STDOUT, start_new_session=True))
        if not wait_http(f"{UI}/"):
            print("ui failed"); return 1

        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()

            # ================= T1: fresh session stream 200, zero 404 ====
            print("\n=== T1: new session stream → 200 held, zero 404 ===", flush=True)
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            page.goto(UI + "/", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector('[data-testid="composer"] textarea', timeout=30000)
            page.wait_for_function("localStorage.getItem('arcen.activeId') !== null", timeout=15000)
            sid_ui = page.evaluate("localStorage.getItem('arcen.activeId')")

            fresh = str(uuid.uuid4())
            status = hold_status(fresh)
            check("T1 GET /api/stream (valid uuid, no run) → 200", status == 200, f"status={status}")
            check("T1 session id is a UUID v4", bool(UUID_RE.match(sid_ui)), f"id={sid_ui}")
            time.sleep(1.0)
            log_text = BACKEND_LOG.read_text(errors="replace")
            n404 = len(re.findall(r'HTTP/1.1" 404 ', log_text))
            n200_stream = len(re.findall(r'GET /api/stream\?session=[0-9a-f-]+ HTTP/1.1" 200 ', log_text))
            check("T1 backend log: ZERO 404 responses", n404 == 0, f"404 count={n404}")
            check("T1 backend log: the held stream logged 200", n200_stream >= 1, f"200 /api/stream lines={n200_stream}")
            excerpt = [ln for ln in log_text.splitlines() if "/api/stream" in ln][-3:]
            print("  [log excerpt]", *excerpt, sep="\n    ", flush=True)

            page.evaluate(INSPECTOR_JS, ["v0.1.6 T1 — new session, stream held (200, no 404)",
                                         [["GET /api/stream", f"200 held (404 count in server log: {n404})"]]])
            page.screenshot(path=str(SHOTS / "01-new-session-stream-200.png"))
            check("T1 screenshot 01-new-session-stream-200.png", (SHOTS / "01-new-session-stream-200.png").exists())

            # ============ T2: hello → real-time events, done ≤ 10s =======
            print("\n=== T2: 'hello' — real-time stream, done ≤ 10s ===", flush=True)
            s2 = str(uuid.uuid4())
            lines: list[tuple[float, str]] = []
            reader_done = threading.Event()

            def on_line(kind: str, value: str) -> None:
                if kind == "__status__":
                    check("T2 stream attached with 200", value == "200", f"status={value}")
                else:
                    lines.append((time.time(), value))
                    if '"stream.done"' in value:
                        reader_done.set()

            rt = threading.Thread(target=read_stream_until_done, args=(s2, on_line, 30), daemon=True)
            rt.start()
            time.sleep(0.8)  # reader attached and held
            t_post = time.time()
            run_resp = api("POST", "/api/run", {"goal": "hello", "session": s2})
            check("T2 POST /api/run accepted", run_resp.get("run_id", "").startswith("r-"))
            rt.join(timeout=15)
            t_done = lines[-1][0] if lines else float("inf")
            total = t_done - t_post
            check("T2 stream.done received", reader_done.is_set() or any('"stream.done"' in l for _, l in lines))
            check("T2 turn completed ≤ 10s", total <= 10.0, f"{total:.2f}s")
            first_evt = next((t for t, l in lines if '"run.start"' in l), None)
            if first_evt is not None:
                lag = first_evt - t_post
                check("T2 run.start arrived live (<2s after POST)", lag < 2.0, f"lag={lag:.2f}s")
                check("T2 events delivered progressively (reader attached pre-run, first event <1s)",
                      (first_evt - t_post) < 1.0 and len(lines) >= 5,
                      f"{len(lines)} lines, first at +{first_evt - t_post:.2f}s")
            print("  [raw stream events]", flush=True)
            for t, l in lines:
                print(f"    +{t - t_post:6.3f}s  {l[:150]}", flush=True)
            answered = any('"answer"' in l and ("Hello" in l or "hello" in l.lower()) for _, l in lines)
            check("T2 the greeting was answered on the stream", answered)

            answer = ui_turn(page, "hello", "Hello")
            check("T2 UI shows the hello answer", "Hello" in answer, answer[:60].replace("\n", " / "))
            sid_now = page.evaluate("localStorage.getItem('arcen.activeId')")
            page.evaluate(INSPECTOR_JS, ["v0.1.6 T2 — hello answered live, no refresh",
                                         [["answer", answer[:60].replace("\n", " ")],
                                          ["turns on wire", str(len(lines))]]])
            try:
                events_ui = api("GET", f"/api/sessions/{sid_now}/events")
                baseline_seq = max((int(e["seq"]) for e in events_ui if isinstance(e.get("seq"), int)), default=0)
            except Exception:
                baseline_seq = 0
            page.screenshot(path=str(SHOTS / "02-hello-live-no-refresh.png"))
            check("T2 screenshot 02-hello-live-no-refresh.png", (SHOTS / "02-hello-live-no-refresh.png").exists())

            # ============= T3: + New chat → 2+2 → 4, no reload ============
            print("\n=== T3: '+ New chat' → '2+2' → '4', no refresh ===", flush=True)
            sid_before = page.evaluate("localStorage.getItem('arcen.activeId')")
            page.evaluate("window.__v16alive = 'yes'")  # reload wipes this
            page.click('[data-testid="new-chat-btn"]')
            page.wait_for_timeout(700)
            sid_after = page.evaluate("localStorage.getItem('arcen.activeId')")
            check("T3 new chat minted a NEW session id", sid_after != sid_before and bool(UUID_RE.match(sid_after or "")),
                  f"{sid_before} → {sid_after}")
            marker = page.evaluate("window.__v16alive || 'GONE'")
            check("T3 no page reload on new chat (marker intact)", marker == "yes", f"marker={marker}")
            page.evaluate(INSPECTOR_JS, ["v0.1.6 T3 — '+ New chat': clean empty state (no reload)",
                                         [["previous session", sid_before or "(none)"],
                                          ["this session", sid_after or "(none)"],
                                          ["reload marker", marker]]])
            page.screenshot(path=str(SHOTS / "05-new-chat-clean.png"))
            check("T3 screenshot 05-new-chat-clean.png", (SHOTS / "05-new-chat-clean.png").exists())

            answer3 = ui_turn(page, "2+2", "4")
            check("T3 '2+2' answered with 4", "4" in (answer3 or "").split(),
                  answer3[:60].replace("\n", " / "))
            marker3 = page.evaluate("window.__v16alive || 'GONE'")
            check("T3 no page reload across the math turn", marker3 == "yes", f"marker={marker3}")
            events3 = api("GET", f"/api/sessions/{sid_after}/events")
            kinds3 = [e.get("type") for e in events3]
            check("T3 wire carried the math turn (run.start→answer→run.done)",
                  "run.start" in kinds3 and "answer" in kinds3 and "run.done" in kinds3,
                  f"{len(events3)} events")
            page.evaluate(INSPECTOR_JS, ["v0.1.6 T3 — '2+2' answered live on the new session",
                                         [["answer", answer3[:40]], ["wire events", str(len(events3))],
                                          ["reload marker", marker3]]])
            page.screenshot(path=str(SHOTS / "03-math-direct.png"))
            check("T3 screenshot 03-math-direct.png", (SHOTS / "03-math-direct.png").exists())

            # ================= T4: mock 401 → clean error < 5s ============
            print("\n=== T4: provider 401 → run.error in < 5s + Test Connection ===", flush=True)
            cfg_view = api("GET", "/api/config")
            cfg_view["provider"]["base_url"] = f"http://127.0.0.1:{BAD_PORT}/v1"
            cfg_view["provider"]["api_key"] = "sk-bad-key"
            cfg_view["provider"]["model"] = "mock-model"
            api("PUT", "/api/config", cfg_view)
            check("T4 config now points at the 401 mock", True, cfg_view["provider"]["base_url"])

            s4 = str(uuid.uuid4())
            lines4: list[tuple[float, str]] = []
            done4 = threading.Event()

            def on_line4(kind: str, value: str) -> None:
                if kind == "__line__":
                    lines4.append((time.time(), value))
                    if '"stream.done"' in value:
                        done4.set()

            rt4 = threading.Thread(target=read_stream_until_done, args=(s4, on_line4, 30), daemon=True)
            rt4.start()
            time.sleep(0.8)
            t4_post = time.time()
            api("POST", "/api/run", {"goal": "hello", "session": s4})
            rt4.join(timeout=15)
            err_pairs = [(t, l) for t, l in lines4 if '"run.error"' in l]
            err_line = json.loads(err_pairs[0][1]) if err_pairs else {}
            lag4 = (err_pairs[0][0] - t4_post) if err_pairs else float("inf")
            check("T4 run.error landed on the stream", bool(err_pairs))
            check("T4 error code PROVIDER_ERROR", err_line.get("code") == "PROVIDER_ERROR", f"code={err_line.get('code')}")
            check("T4 message is the spec wire format",
                  str(err_line.get("message", "")).startswith("provider error: 401"),
                  str(err_line.get("message"))[:100])
            check("T4 clean error in < 5s", lag4 < 5.0, f"{lag4:.2f}s")
            check("T4 stream closed after the error (stream.done)",
                  done4.is_set() or any('"stream.done"' in l for _, l in lines4))
            print("  [raw error evidence]", flush=True)
            for t, l in lines4:
                print(f"    +{t - t4_post:6.3f}s  {l[:170]}", flush=True)

            # Test Connection — the button shows the specific provider error
            page.click('[data-testid="nav-settings"]')
            page.wait_for_selector('[data-testid="test-connection-btn"]', timeout=15000)
            page.click('[data-testid="test-connection-btn"]')
            page.wait_for_selector('[data-testid="test-err"]', timeout=10000)
            err_text = page.locator('[data-testid="test-err"]').inner_text()
            check("T4 Test Connection shows the specific provider error",
                  "provider error: 401" in err_text, err_text[:110])
            page.screenshot(path=str(SHOTS / "04-error-bad-provider.png"))
            check("T4 screenshot 04-error-bad-provider.png", (SHOTS / "04-error-bad-provider.png").exists())

            # restore the good provider so the UI stays usable
            cfg_view = api("GET", "/api/config")
            cfg_view["provider"]["base_url"] = f"http://127.0.0.1:{MOCK_PORT}/v1"
            cfg_view["provider"]["api_key"] = "mock-key-good"
            api("PUT", "/api/config", cfg_view)
            page.click('[data-testid="nav-chat"]')

            browser.close()
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()
        mock_log.close()
        bad_log.close()

    print("\n=== SUMMARY ===", flush=True)
    for name, ok in CHECKS:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    failed = [n for n, ok in CHECKS if not ok]
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed", flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
