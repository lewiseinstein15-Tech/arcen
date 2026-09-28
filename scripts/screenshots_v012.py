#!/usr/bin/env python3
"""ARCEN v0.1.2 screenshot harness — the 3 replan/sandbox approval shots.

Boots the mock provider (:9377) + backend (:3002, custom provider → mock)
+ UI (:5173), then drives real chromium:
  01-replan-continues.png   "run the flaky task" — step 1 fails, DRAFT
                            replans (plan.update), corrected steps run,
                            turn ends Done
  02-replan-terminal.png    "run the doomed task" — always fails, exactly
                            2 replans, clean "Turn failed: replanned
                            twice, still failing" summary
  03-sandbox-state.png      Settings → SANDBOX: boot-detected state lines
                            + amber "process mode" chip (docker-less host)

Every shot is backed by PASS/FAIL checks against the live wire — no
staged screenshots.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "ui" / "screenshots" / "v0.1.2"
MOCK_PORT = 9377
BASE = "http://127.0.0.1:3002"
CHECKS: list[tuple[str, bool]] = []


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
            # any HTTP response (404/501) proves the server is up — the
            # mock provider only serves POST /v1/chat/completions
            return True
        except Exception:
            time.sleep(0.3)
    return False


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


def send_and_wait(page, goal: str, want: str, timeout=90) -> str:
    """Send a goal through the UI composer; wait until a NEW bot message
    (rendered after this send) contains `want`. The UI replays persisted
    history on load, so the pre-send message count is the baseline."""
    page.fill('[data-testid="composer"] textarea', goal)
    baseline = page.locator(".bot-message").count()
    page.keyboard.press("Enter")
    deadline = time.time() + timeout
    text = ""
    while time.time() < deadline:
        if page.locator(".bot-message").count() > baseline:
            text = page.locator(".bot-message").last.inner_text()
            if want in text:
                return text
        time.sleep(0.3)
    return text


def wait_wire_done(sid: str, timeout=20) -> list[dict]:
    """Poll the session wire until the last event is a terminal one —
    the answer renders on the stream slightly BEFORE run.done lands."""
    deadline = time.time() + timeout
    events: list[dict] = []
    while time.time() < deadline:
        events = session_events(sid)
        if events and events[-1].get("type") in ("run.done", "run.error"):
            return events
        time.sleep(0.3)
    return events


def session_events(session: str) -> list[dict]:
    with urllib.request.urlopen(f"{BASE}/api/sessions/{session}/events", timeout=5) as r:
        return json.loads(r.read())


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    cfg_path = Path("/tmp/v012/config.yaml")
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    write_provider_config(cfg_path)

    procs = []
    for pattern in ("uvicorn arcen.server.app", "mock_provider.py", "vite"):
        subprocess.run(["pkill", "-f", pattern], capture_output=True)
    time.sleep(1)
    browser = None
    try:
        procs.append(subprocess.Popen(
            [".venv/bin/python", "scripts/mock_provider.py", str(MOCK_PORT)],
            cwd=ROOT, stdout=open("/tmp/v012-mock.log", "w"), stderr=subprocess.STDOUT,
            start_new_session=True))
        if not wait_http(f"http://127.0.0.1:{MOCK_PORT}/v1"):
            print("mock provider failed"); return 1
        procs.append(subprocess.Popen(
            [".venv/bin/python", "-c",
             "import logging, uvicorn; logging.basicConfig(level=logging.INFO); "
             "from arcen.server.app import app; "
             "uvicorn.run(app, host='0.0.0.0', port=3002)"],
            cwd=ROOT,
            env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "ARCEN_CONFIG_PATH": str(cfg_path)},
            stdout=open("/tmp/v012-backend.log", "w"), stderr=subprocess.STDOUT,
            start_new_session=True))
        if not wait_http(f"{BASE}/api/health"):
            print("backend failed"); return 1

        # T-043 evidence: the boot log printed the four [sandbox] lines
        boot_log = Path("/tmp/v012-backend.log").read_text()
        lines = [ln for ln in boot_log.splitlines() if "[sandbox]" in ln]
        check("boot log has the [sandbox] four-liner",
              any("docker daemon:" in ln for ln in lines)
              and any("image " in ln and ": " in ln for ln in lines)
              and any("backend selected:" in ln for ln in lines)
              and any("reason:" in ln for ln in lines),
              " | ".join(ln.split(" - ")[-1] for ln in lines)[:240])
        check("boot log: docker daemon absent", any("docker daemon: absent" in ln for ln in lines))

        procs.append(subprocess.Popen(
            [shutil.which("npm"), "run", "dev"],
            cwd=ROOT / "ui", stdout=open("/tmp/v012-ui.log", "w"), stderr=subprocess.STDOUT,
            start_new_session=True))
        if not wait_http("http://localhost:5173/"):
            print("ui failed"); return 1

        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto("http://localhost:5173/", wait_until="domcontentloaded")
            page.wait_for_selector('[data-testid="composer"] textarea', timeout=20000)

            # -- 01: flaky task — fail → plan.update → corrected steps → Done
            answer = send_and_wait(page, "run the flaky task: prove replan works", "Done.")
            check("01 turn completed ok (answer carries 'Done.')", "Done." in answer, answer[:90].replace("\n", " / "))
            # the default UI session persists across runs — analyze ONLY the
            # turn this harness just drove (events after the last run.start)
            sessions = json.loads(urllib.request.urlopen(f"{BASE}/api/sessions", timeout=5).read())
            sid = sessions[0]["id"] if sessions else None
            all_events = wait_wire_done(sid) if sid else []
            starts = [i for i, e in enumerate(all_events) if e.get("type") == "run.start"]
            events = all_events[starts[-1]:] if starts else []
            updates = [e for e in events if e.get("type") == "plan.update"]
            failed_cmd = [e for e in events if e.get("type") == "command.done" and not e.get("ok")]
            ok_cmd = [e for e in events if e.get("type") == "command.done" and e.get("ok")]
            check("01 one plan.update on the wire (the replan)", len(updates) == 1, f"count={len(updates)}")
            check("01 a step failed first (command.done ok=false)", len(failed_cmd) >= 1)
            check("01 corrected steps executed after the replan", len(ok_cmd) >= 1)
            dones = [e for e in events if e.get("type") == "run.done"]
            check("01 run.done status ok", bool(dones) and dones[-1].get("status") == "ok")
            page.screenshot(path=str(SHOTS / "01-replan-continues.png"))

            # -- 02: doomed task — 2 replans, clean terminal summary
            page.click('[data-testid="new-chat-btn"]')
            page.wait_for_selector('[data-testid="composer"] textarea', timeout=15000)
            answer2 = send_and_wait(page, "run the doomed task", "replanned twice")
            check("02 terminal summary says 'replanned twice, still failing'",
                  "replanned twice, still failing" in answer2, answer2[:110])
            sessions2 = json.loads(urllib.request.urlopen(f"{BASE}/api/sessions", timeout=5).read())
            sid2 = sessions2[0]["id"] if sessions2 else None
            all_events2 = wait_wire_done(sid2) if sid2 else []
            starts2 = [i for i, e in enumerate(all_events2) if e.get("type") == "run.start"]
            events2 = all_events2[starts2[-1]:] if starts2 else []
            updates2 = [e for e in events2 if e.get("type") == "plan.update"]
            dones2 = [e for e in events2 if e.get("type") == "run.done"]
            check("02 exactly 2 plan.update events (bounded)", len(updates2) == 2, f"count={len(updates2)}")
            check("02 run.done status failed", bool(dones2) and dones2[-1].get("status") == "failed")
            page.screenshot(path=str(SHOTS / "02-replan-terminal.png"))

            # -- 03: Settings → SANDBOX: boot-detected state + amber chip
            page.click('[data-testid="nav-settings"]')
            page.wait_for_selector('[data-testid="settings-sandbox"]', timeout=15000)
            state = page.locator('[data-testid="sandbox-state"]').inner_text()
            chip = page.locator('[data-testid="sandbox-chip"]').inner_text()
            chip_kind = page.locator('[data-testid="sandbox-chip"]').get_attribute("data-chip")
            check("03 sandbox state shows docker daemon: absent", "docker daemon: absent" in state, state[:90])
            check("03 sandbox state shows backend selected", "backend selected:" in state)
            check("03 amber process-mode chip (docker-less host)",
                  chip_kind == "amber" and "process mode" in chip, chip[:80])
            page.locator('[data-testid="settings-sandbox"]').scroll_into_view_if_needed()
            page.screenshot(path=str(SHOTS / "03-sandbox-state.png"))

            browser.close()
            browser = None
    finally:
        if browser is not None:
            browser.close()
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()

    print("\n=== v0.1.2 screenshots ===")
    failed = sum(1 for _, ok in CHECKS if not ok)
    for name, ok in CHECKS:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print(f"{len(CHECKS) - failed}/{len(CHECKS)} checks")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
