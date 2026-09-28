#!/usr/bin/env python3
"""T-040 shot 04 retake — real curl output of /api/sessions, created_at DESC.

Fixes the quoting bug in screenshots_v011.py (jq filter is now
'.[] | [.id, .created_at] | @tsv' — no nested escapes).
"""

from __future__ import annotations

import html
import httpx
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "ui" / "screenshots" / "v0.1.1"
PORT = 3002
BASE = f"http://127.0.0.1:{PORT}"


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
    subprocess.run(["pkill", "-f", "uvicorn arcen.server.app"], capture_output=True)
    time.sleep(1)
    no_provider_cfg = "/tmp/v011-noprovider/config.yaml"  # missing → defaults
    proc = subprocess.Popen(
        [".venv/bin/python", "-m", "uvicorn", "arcen.server.app:app", "--port", str(PORT)],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "ARCEN_CONFIG_PATH": no_provider_cfg},
        stdout=open("/tmp/v011b-backend.log", "w"), stderr=subprocess.STDOUT, start_new_session=True)
    ok = False
    try:
        if not wait_http(f"{BASE}/api/health"):
            print("backend failed")
            return 1
        for name in ("alpha", "beta", "gamma"):
            httpx.post(f"{BASE}/api/run",
                       json={"goal": f"echo {name}", "session": f"s-v011-{name}"}, timeout=10)
        deadline = time.time() + 20
        while time.time() < deadline:
            rows = httpx.get(f"{BASE}/api/sessions", timeout=5).json()
            if sum(1 for r in rows if r["id"].startswith("s-v011-")) >= 3:
                break
            time.sleep(0.3)

        cmd = "curl -s http://localhost:3002/api/sessions | jq -r '.[] | [.id, .created_at] | @tsv'"
        curl = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=15)
        lines = [ln for ln in curl.stdout.splitlines() if "s-v011-" in ln]
        print("curl lines:", lines)
        if curl.stderr.strip():
            print("curl stderr:", curl.stderr.strip()[:200])
        created = []
        for ln in lines:
            parts = ln.split("\t")
            if len(parts) == 2:
                created.append(float(parts[1]))
        desc = created == sorted(created, reverse=True)
        print(f"three sessions: {len(lines) == 3} | descending: {desc}")

        rows_html = html.escape(curl.stdout.strip())
        summary = " → ".join(f"{ln.split(chr(9))[0]} ({ln.split(chr(9))[1]})" for ln in lines)
        page_html = f"""<!doctype html><html><head><meta charset="utf-8">
<style>
  body {{ background: #0A0B0D; color: #E8E6E3; font-family: 'JetBrains Mono', monospace; padding: 48px; }}
  h1 {{ font-size: 20px; color: #FF6B4A; }}
  pre {{ background: #14161A; border: 1px solid #2A2D33; border-radius: 8px; padding: 20px; font-size: 14px; line-height: 1.7; white-space: pre-wrap; }}
  .prompt {{ color: #8A8A8A; }}
  .ok {{ color: #7BC47F; margin-top: 16px; font-size: 13px; }}
  .bad {{ color: #B3412E; margin-top: 16px; font-size: 13px; }}
</style></head><body>
<h1>T-040 — GET /api/sessions is sorted newest-first</h1>
<pre><span class="prompt">$ </span>{html.escape(cmd)}</pre>
<pre>{rows_html}</pre>
<div class="{'ok' if (len(lines) == 3 and desc) else 'bad'}">sessions were created in order alpha → beta → gamma; the API returns newest-first: {html.escape(summary)} — created_at DESC {'✓' if (len(lines) == 3 and desc) else '✗'}</div>
</body></html>"""

        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1100, "height": 620})
            page.set_content(page_html, wait_until="networkidle")
            page.screenshot(path=str(SHOTS / "04-api-sessions-order.png"))
            browser.close()
        ok = len(lines) == 3 and desc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    print("RETAKE", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
