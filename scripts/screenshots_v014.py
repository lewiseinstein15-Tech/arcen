#!/usr/bin/env python3
"""ARCEN v0.1.4 approval harness — settings persistence + model inheritance.

Boots the REAL stack against the REAL ~/.arcen/config.yaml (no config-path
override): mock provider :9377 (OpenAI-compatible stand-in), backend :3002,
vite :5173. Then, in a fresh incognito context:

  01 settings-filled  — dahl fields typed; amber "unsaved changes" chip
  02 settings-saved   — the green "saved ✓" chip after Save (T-051)
  03 config-yaml      — the REAL `cat ~/.arcen/config.yaml` rendered in a
                        terminal page (persistence on disk, T-049)
  04 hello-reply      — real reply through the bridge (endpoint stood in by
                        the local mock; the dahl MODEL NAME stays on every
                        field — no claude-* anywhere)
  05 math-direct      — "2+2" → "4", no bash plan

Every turn-backed capture passes the T-048 staleness guard. The backend
access log must show no 404 for /api/sessions/<uuid>/events (T-052).
"""

from __future__ import annotations

import json
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from screenshot_guard import StaleTurnError, TurnBaseline, assert_fresh_turn

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "ui" / "screenshots" / "v0.1.4"
MOCK_PORT = 9377
BASE = "http://127.0.0.1:3002"
UI = "http://localhost:5173"
CONFIG_PATH = Path.home() / ".arcen" / "config.yaml"
BACKEND_LOG = Path("/tmp/v014-backend.log")

DAHL_URL = "https://inference.dahl.global/v1"
DAHL_MODEL = "deepseek-ai/DeepSeek-V4-Flash-0731"
MOCK_URL = f"http://127.0.0.1:{MOCK_PORT}/v1"

CHECKS: list[tuple[str, bool]] = []
REFUSALS: list[str] = []
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def check(name, ok, detail=""):
    CHECKS.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def wait_http(url, timeout=30):
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


def session_events(session: str) -> list[dict]:
    with urllib.request.urlopen(f"{BASE}/api/sessions/{session}/events", timeout=5) as r:
        return json.loads(r.read())


def wait_wire_done(sid: str, timeout=30) -> list[dict]:
    deadline = time.time() + timeout
    events: list[dict] = []
    while time.time() < deadline:
        try:
            events = session_events(sid)
        except Exception:
            events = []
        if events and events[-1].get("type") in ("run.done", "run.error"):
            return events
        time.sleep(0.3)
    return events


def read_session_id(page) -> str | None:
    return page.evaluate("localStorage.getItem('arcen.activeId')")


def run_turn(page, goal: str, want: str, timeout=60) -> tuple[str, int, list[dict]]:
    """Send a goal, wait for the answer, wait for the wire terminal event."""
    page.fill('[data-testid="composer"] textarea', goal)
    baseline_count = page.locator(".bot-message").count()
    page.keyboard.press("Enter")
    deadline = time.time() + timeout
    text = ""
    while time.time() < deadline:
        if page.locator(".bot-message").count() > baseline_count:
            text = page.locator(".bot-message").last.inner_text()
            if want in text:
                break
        time.sleep(0.3)
    sid = read_session_id(page)
    events = wait_wire_done(sid) if sid else []
    return text, baseline_count, events


def guarded_capture(page, path: Path, shot: str, baseline: TurnBaseline, wire_events: list[dict]) -> bool:
    """T-048: capture ONLY a fresh turn; refuse + record otherwise."""
    try:
        assert_fresh_turn(
            baseline,
            rendered_count=page.locator(".bot-message").count(),
            wire_events=wire_events,
        )
        check(f"{shot} guard: fresh turn (count grew, terminal beyond baseline seq {baseline.max_seq})", True)
    except StaleTurnError as e:
        check(f"{shot} guard: fresh turn", False, e.reason)
        REFUSALS.append(shot)
        print(f"  [REFUSED] {shot} screenshot — {e.reason}")
        return False
    page.screenshot(path=str(path))
    return True


def wait_save_chip_ok(page, timeout=15) -> bool:
    """Wait for the green 'saved ✓' chip (T-051)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            chip = page.locator('[data-testid="save-chip"]')
            if chip.count() > 0 and "saved ✓" in chip.first.inner_text():
                return True
        except Exception:
            pass
        time.sleep(0.15)
    return False


def open_settings(page):
    page.click('[data-testid="nav-settings"]')
    page.wait_for_selector('[data-testid="provider-select"]', timeout=20000)


def boot_stack(procs: list) -> bool:
    """Kill stale processes, boot mock :9377 + backend :3002 + vite :5173.

    The backend reads the REAL ~/.arcen/config.yaml (no override) — phase B
    therefore boots with the endpoint/model the phase-A save persisted."""
    for pattern in ("arcen.server.app", "mock_provider.py", "vite"):
        subprocess.run(["pkill", "-f", pattern], capture_output=True)
    time.sleep(1)
    # the stale-backend trap: health must FAIL right now (nothing on :3002).
    # The pkill pattern above matches the harness's own `python -c` cmdline —
    # a pattern that misses it leaves an old backend squatting on the port,
    # serving pre-fix code while every fresh boot fails to bind silently.
    if wait_http(f"{BASE}/api/health", timeout=2):
        print("FATAL: something is still listening on :3002 — stale backend")
        return False
    procs.append(subprocess.Popen(
        [".venv/bin/python", "scripts/mock_provider.py", str(MOCK_PORT)],
        cwd=ROOT, stdout=open("/tmp/v014-mock.log", "w"), stderr=subprocess.STDOUT,
        start_new_session=True))
    if not wait_http(f"http://127.0.0.1:{MOCK_PORT}/v1"):
        print("mock provider failed"); return False
    procs.append(subprocess.Popen(
        [".venv/bin/python", "-c",
         "import logging, uvicorn; logging.basicConfig(level=logging.INFO); "
         "from arcen.server.app import app; "
         "uvicorn.run(app, host='0.0.0.0', port=3002)"],
        cwd=ROOT,
        stdout=open(BACKEND_LOG, "w"), stderr=subprocess.STDOUT,
        start_new_session=True))
    if not wait_http(f"{BASE}/api/health"):
        print("backend failed"); return False
    procs.append(subprocess.Popen(
        [shutil.which("npm"), "run", "dev"],
        cwd=ROOT / "ui", stdout=open("/tmp/v014-ui.log", "w"), stderr=subprocess.STDOUT,
        start_new_session=True))
    if not wait_http(f"{UI}/"):
        print("ui failed"); return False
    return True


def teardown(procs: list, browser=None) -> None:
    if browser is not None:
        try:
            browser.close()
        except Exception:
            pass
    for p in procs:
        p.terminate()
    for p in procs:
        try:
            p.wait(timeout=5)
        except Exception:
            p.kill()


def main() -> int:
    phase = sys.argv[1] if len(sys.argv) > 1 else "A"
    SHOTS.mkdir(parents=True, exist_ok=True)

    procs: list = []
    browser = None
    try:
        if not boot_stack(procs):
            teardown(procs)
            return 1

        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            page.goto(UI + "/", wait_until="domcontentloaded")
            page.wait_for_selector('[data-testid="composer"] textarea', timeout=20000)
            page.wait_for_function(
                "localStorage.getItem('arcen.activeId') !== null", timeout=10000)
            sid = read_session_id(page)
            check("00 fresh incognito: session id is a UUID (T-045 intact)",
                  bool(sid) and bool(UUID_RE.match(sid)), f"id={sid}")

            if phase == "A":
                run_phase_a(page)
            else:
                run_phase_b(page)

            ctx.close()
            browser.close()
            browser = None
    finally:
        teardown(procs, browser)

    print(f"\n=== v0.1.4 phase {phase} ===")
    failed = sum(1 for _, ok in CHECKS if not ok)
    for name, ok in CHECKS:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print(f"{len(CHECKS) - failed}/{len(CHECKS)} checks")
    if REFUSALS:
        print(f"captures refused by the T-048 staleness guard: {', '.join(REFUSALS)}")
        return 1
    return 1 if failed else 0


def run_phase_a(page) -> None:
    """Fill the dahl settings exactly like the user, save, prove persistence."""
    # -- 01: fill the dahl settings ---------------------------------------
    open_settings(page)
    page.select_option('[data-testid="provider-select"]', "custom")
    page.fill('[data-testid="base-url-input"]', DAHL_URL)
    page.fill('[data-testid="api-key-input"]', "sk-dahl-sandbox-test")
    page.fill('[data-testid="model-input"]', DAHL_MODEL)
    chip = page.locator('[data-testid="save-chip"]')
    check("01 amber 'unsaved changes' chip appears while editing",
          chip.count() > 0 and "unsaved changes" in chip.first.inner_text())
    page.screenshot(path=str(SHOTS / "01-settings-filled.png"), full_page=True)
    check("01 settings-filled.png captured", True)

    # -- 02: Save -> the green saved chip ----------------------------------
    page.click('[data-testid="settings-save"]')
    saved = wait_save_chip_ok(page)
    check("02 green 'saved \u2713' chip visible after Save", saved)
    page.screenshot(path=str(SHOTS / "02-settings-saved.png"), full_page=True)
    check("02 settings-saved.png captured", True)

    # -- 03: the REAL config.yaml on disk (T-049 persistence) --------------
    text = CONFIG_PATH.read_text()
    mode = stat.S_IMODE(CONFIG_PATH.stat().st_mode)
    check("03 config.yaml: provider.name = custom", "name: custom" in text)
    check("03 config.yaml: provider.base_url = dahl", f"base_url: {DAHL_URL}" in text)
    check("03 config.yaml: provider.model = the dahl model", f"model: {DAHL_MODEL}" in text)
    check("03 config.yaml: api_key persisted (chmod 600)",
          "api_key: sk-dahl-sandbox-test" in text and mode == 0o600, f"mode={oct(mode)}")
    check("03 config.yaml: agents.*.model null (inherit)", text.count("model: null") >= 3)
    check("03 config.yaml: NO claude-* anywhere", "claude" not in text)
    term = f"""<!DOCTYPE html><html><head><style>
body {{ background:#0d1117; color:#c9d1d9; font:14px/1.55 ui-monospace,Menlo,monospace; padding:28px; }}
.bar {{ color:#8b949e; border-bottom:1px solid #30363d; padding-bottom:8px; margin-bottom:14px; }}
.p {{ color:#7ee2a8; }} pre {{ white-space:pre-wrap; }}
</style></head><body>
<div class="bar">T-049 harness \u2014 terminal \u00b7 user@laptop</div>
<div><span class="p">$</span> cat ~/.arcen/config.yaml &amp;&amp; stat -c '%a' ~/.arcen/config.yaml</div>
<pre>{text.replace('&', '&amp;').replace('<', '&lt;')}
{oct(mode)[2:]}</pre>
<div><span class="p">$</span> _</div>
</body></html>"""
    page.set_content(term)
    page.wait_for_timeout(300)
    page.screenshot(path=str(SHOTS / "03-config-yaml.png"), full_page=True)
    check("03 config-yaml.png captured (real cat output)", True)

    # -- endpoint stand-in for the chat leg: the local mock ----------------
    # The dahl MODEL NAME stays; the sandbox has no dahl credentials, so the
    # chat leg runs against the local OpenAI-compatible mock (documented in
    # the report). The second save also re-proves the saved-chip flow.
    page.goto(UI + "/", wait_until="domcontentloaded")
    page.wait_for_selector('[data-testid="composer"] textarea', timeout=20000)
    open_settings(page)
    page.fill('[data-testid="base-url-input"]', MOCK_URL)
    page.click('[data-testid="settings-save"]')
    check("A-final second save (mock endpoint) -> saved \u2713", wait_save_chip_ok(page))


def run_phase_b(page) -> None:
    """Rebooted on the persisted config: verify inherit UI, probe, chat."""
    # the backend booted with the SAVED config (mock endpoint + dahl model)
    text = CONFIG_PATH.read_text()
    check("B0 config.yaml survived the restart: dahl model + mock endpoint",
          f"model: {DAHL_MODEL}" in text and f"base_url: {MOCK_URL}" in text)

    open_settings(page)
    stored = page.locator('[data-testid="model-input"]').input_value()
    check("B0 Model Name field shows the persisted dahl model", stored == DAHL_MODEL, stored)
    check("B0 AGENTS placeholders read 'inherit from provider' (T-050)",
          page.locator('[data-testid="draft-model"]').get_attribute("placeholder") == "inherit from provider")
    check("B0 clean load: no save-chip (nothing unsaved)",
          page.locator('[data-testid="save-chip"]').count() == 0)

    page.click('[data-testid="test-connection-btn"]')
    # wait for EITHER outcome — a timeout with no probe response means the
    # click never fired; test-err text names the failure
    outcome = ""
    try:
        page.wait_for_selector('[data-testid="test-ok"], [data-testid="test-err"]', timeout=20000)
        if page.locator('[data-testid="test-ok"]').count() > 0:
            outcome = "ok: " + page.locator('[data-testid="test-ok"]').inner_text()
        else:
            outcome = "err: " + page.locator('[data-testid="test-err"]').inner_text()
    except Exception as e:
        outcome = f"no probe outcome at all ({type(e).__name__})"
    check("B0 Test Connection green (model probe through the bridge shape)",
          outcome.startswith("ok:"), outcome[:160])

    # -- 04: hello -> a real reply through the bridge -----------------------
    page.click('[data-testid="nav-chat"]')
    page.wait_for_selector('[data-testid="composer"] textarea', timeout=20000)
    answer1, base1, events1 = run_turn(page, "hello", "Hello! I'm ARCEN")
    check("04 hello answered (not the no-provider refusal)",
          "Hello! I'm ARCEN" in answer1, answer1[:70].replace("\n", " / "))
    dones1 = [e for e in events1 if e.get("type") == "run.done"]
    check("04 run.done status ok", bool(dones1) and dones1[-1].get("status") == "ok")
    guarded_capture(page, SHOTS / "04-hello-reply.png", "04",
                    TurnBaseline(rendered_count=base1, max_seq=0), events1)

    # -- 05: 2+2 -> "4", no bash plan ----------------------------------------
    seq1 = max((int(e["seq"]) for e in events1 if isinstance(e.get("seq"), int)), default=0)
    answer2, base2, events2 = run_turn(page, "2+2", "4")
    answers = [e for e in events2 if e.get("type") == "answer"]
    wire_text = str(answers[-1].get("text", "")) if answers else answer2
    check("05 2+2 -> 4 (wire answer text)", wire_text.strip() == "4",
          wire_text[:70].replace("\n", " / "))
    bash_steps = [e for e in events2 if e.get("type") in ("plan", "plan.update")]
    check("05 no bash plan (direct answer)", not bash_steps)
    guarded_capture(page, SHOTS / "05-math-direct.png", "05",
                    TurnBaseline(rendered_count=base2, max_seq=seq1), events2)

    # -- T-052: no 404s for /api/sessions/<uuid>/events ----------------------
    # uvicorn colorizes access-log status codes — strip ANSI before matching
    ansi = re.compile(r"\x1b\[[0-9;]*m")
    log = "\n".join(ansi.sub("", ln) for ln in BACKEND_LOG.read_text(errors="replace").splitlines())
    not_founds = [ln for ln in log.splitlines()
                  if "/api/sessions/" in ln and "/events" in ln and " 404 " in ln]
    check("05 server log: no 404 for /api/sessions/<uuid>/events", not not_founds,
          not_founds[0][:110] if not_founds else "")
    replays = [ln for ln in log.splitlines()
               if "/api/sessions/" in ln and "/events" in ln and " 200 " in ln]
    check("05 server log: fresh-session event replays return 200", bool(replays),
          f"{len(replays)} x 200 on /api/sessions/*/events")


if __name__ == "__main__":
    sys.exit(main())
