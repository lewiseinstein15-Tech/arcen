#!/usr/bin/env python3
"""ARCEN v0.1.3 screenshot harness — T-045/T-046/T-048 approval shots.

Boots the mock provider (:9377) + backend (:3002, custom provider → mock)
+ UI (:5173), then drives real chromium in SEPARATE browser contexts
(simulated incognito windows):

  01-fresh-session-uuid.png  a fresh context: localStorage arcen.activeId
                             is a generated UUID (not "s-ui"), shown by a
                             harness inspector overlay reading the REAL
                             localStorage; backed by a real answered turn
  _turn2-distinct.png        the second back-to-back run on the same
                             session — a DISTINCT turn (T-048 verify)
  02-two-contexts.png        a second independent context with a DIFFERENT
                             UUID; overlay shows both ids side by side

T-048 guard: every turn-backed capture passes screenshot_guard first —
the rendered message count must have grown past the pre-send baseline AND
the wire must carry a fresh terminal event (seq beyond the baseline). A
stale stream is refused (no capture, reason printed, exit non-zero). The
harness also proves the refusal live: after a completed turn it re-runs
the guard against an unchanged baseline and expects StaleTurnError.

Every shot is backed by PASS/FAIL checks against the live wire — no
staged screenshots.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from screenshot_guard import StaleTurnError, TurnBaseline, assert_fresh_turn

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "ui" / "screenshots" / "v0.1.3"
MOCK_PORT = 9377
BASE = "http://127.0.0.1:3002"
UI = "http://localhost:5173"
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


# A devtools-style inspector overlay showing the context's REAL localStorage
# value. The assertions around it are enforced against the live values — the
# overlay only renders what the harness actually read and checked.
INSPECTOR_JS = """
(args) => {
  const [label, extraRows] = args;
  const v = localStorage.getItem('arcen.activeId') ?? '(none)';
  const isUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(v);
  const rows = [
    ['key', 'arcen.activeId'],
    ['value', v],
    ['is UUID v4', isUuid ? 'YES' : 'NO'],
    ['is "s-ui"', v === 's-ui' ? 'YES (BUG)' : 'no'],
    ...extraRows,
  ];
  const box = document.createElement('div');
  box.id = 't045-inspector';
  box.style.cssText = 'position:fixed;top:12px;right:12px;z-index:99999;'
    + 'background:#111418;color:#d7dde6;border:1px solid #3a414b;border-radius:8px;'
    + 'padding:10px 14px;font:12px/1.7 ui-monospace,Menlo,monospace;min-width:360px;'
    + 'box-shadow:0 8px 24px rgba(0,0,0,.45)';
  box.innerHTML = '<div style="color:#8b949e;border-bottom:1px solid #3a414b;'
    + 'margin-bottom:6px;padding-bottom:4px">' + label + '</div>'
    + rows.map(([k, val]) => `<div><span style="color:#7ee2a8">${k}</span>: ${val}</div>`).join('');
  document.body.appendChild(box);
  return v;
}
"""


def read_session_id(page) -> str | None:
    """The REAL id in this context's localStorage (T-045 key)."""
    return page.evaluate("localStorage.getItem('arcen.activeId')")


def run_turn(page, goal: str, want: str, timeout=60) -> tuple[str, int, list[dict]]:
    """Send a goal, wait for the answer to render, wait for the wire to go
    terminal. Returns (answer_text, pre_send_message_count, wire_events)."""
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


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    cfg_path = Path("/tmp/v013/config.yaml")
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
            cwd=ROOT, stdout=open("/tmp/v013-mock.log", "w"), stderr=subprocess.STDOUT,
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
            stdout=open("/tmp/v013-backend.log", "w"), stderr=subprocess.STDOUT,
            start_new_session=True))
        if not wait_http(f"{BASE}/api/health"):
            print("backend failed"); return 1
        procs.append(subprocess.Popen(
            [shutil.which("npm"), "run", "dev"],
            cwd=ROOT / "ui", stdout=open("/tmp/v013-ui.log", "w"), stderr=subprocess.STDOUT,
            start_new_session=True))
        if not wait_http(f"{UI}/"):
            print("ui failed"); return 1

        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()

            # ── context A: a fresh incognito window ─────────────────────
            ctx_a = browser.new_context(viewport={"width": 1440, "height": 900})
            page_a = ctx_a.new_page()
            page_a.goto(UI + "/", wait_until="domcontentloaded")
            page_a.wait_for_selector('[data-testid="composer"] textarea', timeout=20000)
            # give the boot resolution a beat to persist the generated id
            page_a.wait_for_function(
                "localStorage.getItem('arcen.activeId') !== null", timeout=10000)

            id_a = read_session_id(page_a)
            check("01 fresh context: localStorage arcen.activeId is a UUID",
                  bool(id_a) and bool(UUID_RE.match(id_a)), f"id={id_a}")
            check("01 fresh context: the id is NOT 's-ui'", id_a != "s-ui")

            # a real turn proves the id is live: the run POSTs to it and the
            # wire events land on that session
            answer1, base1, events1 = run_turn(page_a, "hello", "Hello! I'm ARCEN")
            check("01 turn answered on the generated session",
                  "Hello! I'm ARCEN" in answer1 and bool(events1)
                  and events1[-1].get("type") == "run.done",
                  answer1[:70].replace("\n", " / "))
            dones1 = [e for e in events1 if e.get("type") == "run.done"]
            check("01 run.done status ok", bool(dones1) and dones1[-1].get("status") == "ok")

            page_a.evaluate(
                INSPECTOR_JS,
                ["T-045 harness inspector — context A (fresh incognito)", []],
            )
            ok01 = guarded_capture(
                page_a, SHOTS / "01-fresh-session-uuid.png", "01",
                TurnBaseline(rendered_count=base1, max_seq=0), events1,
            )

            # ── T-048 verify: harness twice back-to-back, distinct turns ──
            base_seq_1 = max((int(e["seq"]) for e in events1 if isinstance(e.get("seq"), int)), default=0)
            answer2, base2, events2 = run_turn(page_a, "hello again", "direct answer to")
            check("02 second back-to-back run answered", "direct answer to" in answer2,
                  answer2[:70].replace("\n", " / "))
            ok02 = guarded_capture(
                page_a, SHOTS / "_turn2-distinct.png", "02 (run 2, same session)",
                TurnBaseline(rendered_count=base2, max_seq=base_seq_1), events2,
            )
            fresh_dones = [int(e.get("seq", 0)) for e in events2
                           if e.get("type") == "run.done" and int(e.get("seq", 0)) > base_seq_1]
            check("02 the two runs captured DISTINCT turns (fresh run.done beyond run 1)",
                  bool(fresh_dones),
                  f"run 1 ended at seq {base_seq_1}; run 2 fresh done at seq {fresh_dones}")

            # the refusal path, live: guard against an UNCHANGED baseline —
            # nothing new rendered → must refuse (harness would exit non-zero)
            try:
                assert_fresh_turn(
                    TurnBaseline(rendered_count=page_a.locator(".bot-message").count(), max_seq=base_seq_1),
                    rendered_count=page_a.locator(".bot-message").count(),
                    wire_events=events2,
                )
                check("02 guard refuses a stale capture → exit non-zero", False,
                      "StaleTurnError was NOT raised")
            except StaleTurnError as e:
                check("02 guard refuses a stale capture → exit non-zero",
                      "did not grow past baseline" in e.reason, e.reason[:110])

            # ── context B: a SECOND fresh incognito window ──────────────
            ctx_b = browser.new_context(viewport={"width": 1440, "height": 900})
            page_b = ctx_b.new_page()
            page_b.goto(UI + "/", wait_until="domcontentloaded")
            page_b.wait_for_selector('[data-testid="composer"] textarea', timeout=20000)
            page_b.wait_for_function(
                "localStorage.getItem('arcen.activeId') !== null", timeout=10000)
            id_b = read_session_id(page_b)
            check("03 second incognito context: its own UUID",
                  bool(id_b) and bool(UUID_RE.match(id_b)), f"id={id_b}")
            check("03 the two contexts have DIFFERENT session ids",
                  bool(id_a) and bool(id_b) and id_a != id_b, f"A={id_a}  B={id_b}")

            answer_b, base_b, events_b = run_turn(page_b, "hey there", "direct answer to")
            check("03 context B ran its own turn",
                  "direct answer to" in answer_b and bool(events_b)
                  and events_b[-1].get("type") == "run.done")
            goals_b = {e.get("goal") for e in events_b if e.get("type") == "run.start"}
            check("03 B's wire carries ONLY B's turn (no bleed from A)",
                  goals_b == {"hey there"},
                  f"goals on B's wire={sorted(goals_b)}")

            page_b.evaluate(
                INSPECTOR_JS,
                ["T-045 harness inspector — context B (2nd incognito)",
                 [["context A id", id_a or "(none)"],
                  ["different ids", "YES" if id_a != id_b else "NO"]],
                 ],
            )
            ok03 = guarded_capture(
                page_b, SHOTS / "02-two-contexts.png", "03",
                TurnBaseline(rendered_count=base_b, max_seq=0), events_b,
            )

            ctx_a.close()
            ctx_b.close()
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

    print("\n=== v0.1.3 screenshots ===")
    failed = sum(1 for _, ok in CHECKS if not ok)
    for name, ok in CHECKS:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print(f"{len(CHECKS) - failed}/{len(CHECKS)} checks")
    if REFUSALS:
        print(f"captures refused by the T-048 staleness guard: {', '.join(REFUSALS)}")
        return 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
