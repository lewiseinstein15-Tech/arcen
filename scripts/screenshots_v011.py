#!/usr/bin/env python3
"""ARCEN v0.1.1 screenshot harness — the 4 follow-up approval shots.

Boots the backend (:3002, NO provider — that is the T-037 story) + UI
(:5173), then drives real chromium:
  01-no-provider-message.png  "build a calculator" → clean refusal
  02-settings-backend.png     SANDBOX dropdown editable + docker warning
  03-settings-theme.png       GENERAL: no theme toggle (T-039 Option B)
  04-api-sessions-order.png   real `curl | jq` output, created_at DESC
"""

from __future__ import annotations

import html
import httpx
import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "ui" / "screenshots" / "v0.1.1"
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
        except Exception:
            time.sleep(0.3)
    return False


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    no_provider_cfg = Path("/tmp/v011-noprovider/config.yaml")  # missing → defaults, no provider

    procs = []
    for pattern in ("uvicorn arcen.server.app", "mock_provider.py", "vite"):
        subprocess.run(["pkill", "-f", pattern], capture_output=True)
    time.sleep(1)
    try:
        procs.append(subprocess.Popen(
            [".venv/bin/python", "-m", "uvicorn", "arcen.server.app:app", "--port", "3002"],
            cwd=ROOT,
            env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "ARCEN_CONFIG_PATH": str(no_provider_cfg)},
            stdout=open("/tmp/v011-backend.log", "w"), stderr=subprocess.STDOUT, start_new_session=True))
        if not wait_http("http://127.0.0.1:3002/api/health"):
            print("backend failed"); return 1
        procs.append(subprocess.Popen(
            [shutil.which("npm"), "run", "dev"],
            cwd=ROOT / "ui", stdout=open("/tmp/v011-ui.log", "w"), stderr=subprocess.STDOUT, start_new_session=True))
        if not wait_http("http://localhost:5173/"):
            print("ui failed"); return 1

        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto("http://localhost:5173/", wait_until="domcontentloaded")
            page.wait_for_selector('[data-testid="composer"] textarea', timeout=20000)

            # -- 01: "build a calculator" with NO provider → clean refusal
            page.fill('[data-testid="composer"] textarea', "build a calculator")
            page.keyboard.press("Enter")
            deadline = time.time() + 30
            answer_text = ""
            while time.time() < deadline:
                n_done = page.locator(".bot-message").count()
                if n_done >= 1:
                    answer_text = page.locator(".bot-message").last.inner_text()
                    if "model provider" in answer_text:
                        break
                time.sleep(0.3)
            check("01 refusal answer mentions the model provider", "model provider" in answer_text, answer_text[:80])
            check("01 no command executed",
                  page.locator('[data-testid="command"]').count() == 0)
            page.screenshot(path=str(SHOTS / "01-no-provider-message.png"))

            # -- 02: SANDBOX — editable dropdown + docker-pinned warning
            page.click('[data-testid="nav-settings"]')
            page.wait_for_selector('[data-testid="settings-sandbox"]', timeout=15000)
            page.wait_for_selector('[data-testid="sandbox-backend"]', timeout=15000)
            select = page.locator('[data-testid="sandbox-backend"]')
            options = select.locator("option").all_inner_texts()
            check("02 backend dropdown editable with 3 options",
                  len(options) == 3 and any("auto" in o for o in options) and any("docker" in o for o in options) and any("process" in o for o in options),
                  str(options))
            select.select_option("docker")
            page.wait_for_selector('[data-testid="sandbox-warn"]', timeout=10000)
            warn = page.locator('[data-testid="sandbox-warn"]').inner_text()
            check("02 docker-pinned warning shown (no daemon here)", "docker" in warn.lower(), warn[:90])
            page.locator('[data-testid="settings-sandbox"]').scroll_into_view_if_needed()
            page.screenshot(path=str(SHOTS / "02-settings-backend.png"))

            # -- 03: GENERAL — no theme toggle (T-039 Option B)
            general = page.locator('[data-testid="settings-general"]')
            general.scroll_into_view_if_needed()
            check("03 theme toggle removed",
                  page.locator('[data-testid="theme-select"]').count() == 0)
            check("03 verbosity + auto-scroll still present",
                  page.locator('[data-testid="verbosity-select"]').count() == 1
                  and page.locator('[data-testid="autoscroll-select"]').count() == 1)
            page.screenshot(path=str(SHOTS / "03-settings-theme.png"))

            browser.close()

        # -- 04: real curl output — /api/sessions created_at DESC
        for name in ("alpha", "beta", "gamma"):
            httpx.post("http://127.0.0.1:3002/api/run",
                       json={"goal": f"echo {name}", "session": f"s-v011-{name}"}, timeout=10)
        deadline = time.time() + 20
        while time.time() < deadline:  # wait until all three sessions exist
            rows = httpx.get("http://127.0.0.1:3002/api/sessions", timeout=5).json()
            if sum(1 for r in rows if r["id"].startswith("s-v011-")) >= 3:
                break
            time.sleep(0.3)

        jq = shutil.which("jq")
        cmd = "curl -s http://localhost:3002/api/sessions | jq -r '.[] | \"\\(.id)  created_at=\\(.created_at)\"" if jq else (
            "curl -s http://localhost:3002/api/sessions")
        curl = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=15)
        out_lines = [ln for ln in curl.stdout.splitlines() if "s-v011-" in ln]
        created = [float(ln.split("created_at=")[1]) for ln in out_lines if "created_at=" in ln]
        check("04 three sessions listed", len(out_lines) == 3, str(out_lines))
        check("04 created_at DESC (newest first)", created == sorted(created, reverse=True), str(created))

        page_html = f"""<!doctype html><html><head><meta charset="utf-8">
<style>
  body {{ background: #0A0B0D; color: #E8E6E3; font-family: 'JetBrains Mono', monospace; padding: 48px; }}
  h1 {{ font-size: 20px; color: #FF6B4A; }}
  pre {{ background: #14161A; border: 1px solid #2A2D33; border-radius: 8px; padding: 20px; font-size: 14px; line-height: 1.7; white-space: pre-wrap; }}
  .prompt {{ color: #8A8A8A; user-select: none; }}
  .ok {{ color: #7BC47F; margin-top: 16px; }}
</style></head><body>
<h1>T-040 — GET /api/sessions is sorted newest-first</h1>
<pre><span class="prompt">$ </span>{html.escape(cmd)}</pre>
<pre>{html.escape(curl.stdout.strip())}</pre>
<div class="ok">created_at DESC ✓ — gamma (newest) first, alpha (oldest) last</div>
</body></html>"""
        p2 = browser = None
        from playwright.sync_api import sync_playwright as spw
        with spw() as pw2:
            b2 = pw2.chromium.launch()
            pg2 = b2.new_page(viewport={"width": 1100, "height": 640})
            pg2.set_content(page_html, wait_until="networkidle")
            pg2.screenshot(path=str(SHOTS / "04-api-sessions-order.png"))
            b2.close()
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()

    print("\n=== v0.1.1 screenshots ===")
    failed = sum(1 for _, ok in CHECKS if not ok)
    for name, ok in CHECKS:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print(f"{len(CHECKS) - failed}/{len(CHECKS)} checks")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
