#!/usr/bin/env python3
"""ARCEN v0.1.5 verification — env vars seed Settings on boot (T-055).

Boots the REAL stack against the REAL ~/.arcen/config.yaml with the local
mock provider (:9377) standing in for the endpoint, and walks the four
boot phases the ticket specifies:

  A  first boot with ARCEN_MODEL_* set, no config file
     → "[config] seeded from env:" in the server log (key masked, never full)
     → ~/.arcen/config.yaml written with the four provider fields
     → Settings shows every field auto-populated (P4 screenshot)
     → "hello" answered through the bridge, "2+2" → "4"
  B  restart with the same env (config now complete)
     → NO seed line, config.yaml byte-identical (write-once)
  C  provider.model manually emptied, restart with env
     → re-seeds ONLY that field; api_key/base_url untouched
  D  no env vars, no config file (P5 proof)
     → no seed line, no file created, Settings/API all empty

The DAHL model name stays on every field and in every assertion —
no claude-* anywhere (v0.1.4 rule).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from screenshot_guard import StaleTurnError, TurnBaseline  # noqa: E402
from screenshots_v014 import (  # noqa: E402  (reused harness helpers)
    check,
    read_session_id,
    run_turn,
    wait_http,
    wait_wire_done,
)

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "ui" / "screenshots" / "v0.1.5"
MOCK_PORT = 9377
BASE = "http://127.0.0.1:3002"
UI = "http://localhost:5173"
CONFIG_PATH = Path.home() / ".arcen" / "config.yaml"
BACKEND_LOG = Path("/tmp/v055-backend.log")
MOCK_LOG = Path("/tmp/v055-mock.log")
UI_LOG = Path("/tmp/v055-ui.log")

DAHL_MODEL = "deepseek-ai/DeepSeek-V4-Flash-0731"
VERIFY_KEY = "dahl_verify_key_1234567890abcd"
MASKED_KEY = "dahl...abcd"  # mask_secret(first4 + "..." + last4)
MOCK_URL = f"http://127.0.0.1:{MOCK_PORT}/v1"

ENV_SEED = {
    "ARCEN_MODEL_PROVIDER": "custom",
    "ARCEN_MODEL_BASE_URL": MOCK_URL,
    "ARCEN_MODEL_API_KEY": VERIFY_KEY,
    "ARCEN_MODEL_NAME": DAHL_MODEL,
}

ANSI = re.compile(r"\x1b\[[0-9;]*m")

procs: list[subprocess.Popen] = []


def backend_log() -> str:
    text = BACKEND_LOG.read_text(errors="replace") if BACKEND_LOG.exists() else ""
    return ANSI.sub("", text)


def kill(pattern: str) -> None:
    subprocess.run(["pkill", "-f", pattern], capture_output=True)


def teardown() -> None:
    for p in procs:
        p.terminate()
    for pattern in ("arcen.server.app", "mock_provider.py", "vite"):
        kill(pattern)
    time.sleep(1)


def start_backend(env: dict[str, str]) -> None:
    """(Re)start the backend on :3002 with exactly the given ARCEN env."""
    kill("arcen.server.app")
    time.sleep(1)
    if wait_http(f"{BASE}/api/health", timeout=2):
        raise SystemExit("FATAL: stale backend still listening on :3002")
    child_env = {**os.environ, **env}
    procs.append(subprocess.Popen(
        [".venv/bin/python", "-c",
         "import logging, uvicorn; logging.basicConfig(level=logging.INFO); "
         "from arcen.server.app import app; "
         "uvicorn.run(app, host='0.0.0.0', port=3002)"],
        cwd=ROOT, env=child_env,
        stdout=open(BACKEND_LOG, "w"), stderr=subprocess.STDOUT,  # truncate per boot
        start_new_session=True))
    if not wait_http(f"{BASE}/api/health"):
        print(backend_log()[-800:])
        raise SystemExit("FATAL: backend failed to boot")


def start_stack() -> None:
    for pattern in ("arcen.server.app", "mock_provider.py", "vite"):
        kill(pattern)
    time.sleep(1)
    procs.append(subprocess.Popen(
        [".venv/bin/python", "scripts/mock_provider.py", str(MOCK_PORT)],
        cwd=ROOT, stdout=open(MOCK_LOG, "w"), stderr=subprocess.STDOUT,
        start_new_session=True))
    if not wait_http(f"http://127.0.0.1:{MOCK_PORT}/v1"):
        raise SystemExit("FATAL: mock provider failed")
    procs.append(subprocess.Popen(
        [shutil.which("npm"), "run", "dev"],
        cwd=ROOT / "ui", stdout=open(UI_LOG, "w"), stderr=subprocess.STDOUT,
        start_new_session=True))
    if not wait_http(f"{UI}/"):
        raise SystemExit("FATAL: UI failed to boot")


def get_json(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=5) as r:
        import json
        return json.loads(r.read())


def main() -> int:
    from playwright.sync_api import sync_playwright

    SHOTS.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        CONFIG_PATH.unlink()  # the env-vars-are-source-of-truth precondition
    start_stack()
    results: list[tuple[str, bool]] = []

    def finish(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, bool(ok)))
        check(name, ok, detail)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context().new_page()

        # -- phase A: first boot with env, no config file --------------------
        print("\n== phase A: first boot with ARCEN_MODEL_* set, no config file")
        start_backend(ENV_SEED)
        log = backend_log()
        seed_lines = [ln for ln in log.splitlines() if "[config] seeded from env:" in ln]
        finish("A1 seed line in server log", len(seed_lines) == 1)
        finish("A2 log masks the key (dahl...abcd, never the raw value)",
               MASKED_KEY in log and VERIFY_KEY not in log)
        seeded = seed_lines[0] if seed_lines else "(no line)"
        print(f"       boot line: {seeded.strip()[:160]}")

        import yaml

        finish("A3 config.yaml written with the four provider fields",
               CONFIG_PATH.exists()
               and yaml.safe_load(CONFIG_PATH.read_text())["provider"]["model"] == DAHL_MODEL
               and yaml.safe_load(CONFIG_PATH.read_text())["provider"]["api_key"] == VERIFY_KEY
               and yaml.safe_load(CONFIG_PATH.read_text())["provider"]["base_url"] == MOCK_URL)

        cfg = get_json("/api/config")
        prov = cfg.get("provider", {})
        finish("A4 GET /api/config: env values + redacted key",
               prov.get("base_url") == MOCK_URL and prov.get("model") == DAHL_MODEL
               and prov.get("api_key") == "<redacted>")

        page.goto(f"{UI}", wait_until="domcontentloaded")
        page.wait_for_selector('[data-testid="nav-settings"]', timeout=20000)
        page.click('[data-testid="nav-settings"]')
        page.wait_for_selector('[data-testid="provider-select"]', timeout=20000)
        page.wait_for_timeout(400)  # let fields settle
        got = {
            "provider": page.locator('[data-testid="provider-select"]').input_value(),
            "base_url": page.locator('[data-testid="base-url-input"]').input_value(),
            "model": page.locator('[data-testid="model-input"]').input_value(),
            "key_placeholder": page.locator('[data-testid="api-key-input"]').get_attribute("placeholder") or "",
        }
        finish("A5 Settings auto-populated (provider/base_url/model)",
               got["provider"] == "custom" and got["base_url"] == MOCK_URL
               and got["model"] == DAHL_MODEL)
        finish("A6 API key field masked but present",
               "stored" in got["key_placeholder"] and VERIFY_KEY not in got["key_placeholder"])
        page.screenshot(path=str(SHOTS / "settings-env-seeded.png"))

        # Test Connection through the mock, then hello + 2+2 through the bridge
        page.click('[data-testid="test-connection-btn"]')
        ok_probe = True
        try:
            page.wait_for_selector('[data-testid="test-ok"]', timeout=20000)
        except Exception:
            ok_probe = False
        finish("A7 Test Connection green (seeded config probes OK)", ok_probe)

        page.click('[data-testid="nav-chat"]')
        page.wait_for_selector('[data-testid="composer"] textarea', timeout=20000)
        answer1, base1, events1 = run_turn(page, "hello", "Hello! I'm ARCEN")
        finish("A8 'hello' answered (no 'I need a model provider' refusal)",
               "Hello! I'm ARCEN" in answer1, answer1[:70].replace("\n", " / "))
        page.screenshot(path=str(SHOTS / "hello-reply.png"))
        answer2, _base2, events2 = run_turn(page, "2+2", "4")
        finish("A9 '2+2' → 4, no bash plan",
               "4" in answer2 and not [e for e in events2 if e.get("type") in ("plan", "plan.update")],
               answer2[:40].replace("\n", " / "))
        page.screenshot(path=str(SHOTS / "math-direct.png"))
        _ = TurnBaseline(rendered_count=base1, max_seq=0)  # guard helpers kept imported

        # -- phase B: restart with the same env — config wins ----------------
        print("\n== phase B: restart with env — no re-seed, file untouched")
        bytes_before = CONFIG_PATH.read_bytes()
        start_backend(ENV_SEED)
        log = backend_log()
        restart_lines = [ln for ln in log.splitlines() if "[config] seeded from env:" in ln]
        finish("B1 no seed line on restart", not restart_lines)
        finish("B2 config.yaml byte-identical after restart",
               CONFIG_PATH.read_bytes() == bytes_before)
        prov = get_json("/api/config").get("provider", {})
        finish("B3 Settings/API still show the values",
               prov.get("base_url") == MOCK_URL and prov.get("model") == DAHL_MODEL)

        # -- phase C: empty one field → only that field re-seeds -------------
        print("\n== phase C: provider.model emptied → re-seeds ONLY that field")
        doc = yaml.safe_load(CONFIG_PATH.read_text())
        kept_key, kept_url = doc["provider"]["api_key"], doc["provider"]["base_url"]
        doc["provider"]["model"] = ""
        CONFIG_PATH.write_text(yaml.safe_dump(doc, sort_keys=False))
        start_backend(ENV_SEED)
        log = backend_log()
        seed_lines = [ln for ln in log.splitlines() if "[config] seeded from env:" in ln]
        finish("C1 seed line present after partial emptiness", len(seed_lines) == 1)
        doc = yaml.safe_load(CONFIG_PATH.read_text())
        finish("C2 only provider.model re-seeded",
               doc["provider"]["model"] == DAHL_MODEL
               and doc["provider"]["api_key"] == kept_key
               and doc["provider"]["base_url"] == kept_url)
        finish("C3 GET /api/config shows the re-seeded model",
               get_json("/api/config")["provider"]["model"] == DAHL_MODEL)

        # -- phase D: no env, no file → everything empty (P5 proof) ----------
        print("\n== phase D: env unset + no file → nothing seeded, nothing written")
        CONFIG_PATH.unlink()
        start_backend({k: "" for k in ENV_SEED})  # env vars explicitly emptied
        log = backend_log()
        finish("D1 no seed line without env vars",
               not [ln for ln in log.splitlines() if "[config] seeded from env:" in ln])
        finish("D2 config.yaml NOT created", not CONFIG_PATH.exists())
        prov = get_json("/api/config").get("provider", {})
        finish("D3 API: provider fields all empty",
               prov.get("base_url") == "" and prov.get("model") == ""
               and prov.get("api_key") in ("", "<redacted>"))

        page.goto(f"{UI}", wait_until="domcontentloaded")
        page.wait_for_selector('[data-testid="nav-settings"]', timeout=20000)
        page.click('[data-testid="nav-settings"]')
        page.wait_for_selector('[data-testid="model-input"]', timeout=20000)
        page.wait_for_timeout(400)
        finish("D4 Settings shows empty fields (env was the source in phase A)",
               page.locator('[data-testid="model-input"]').input_value() == ""
               and page.locator('[data-testid="base-url-input"]').input_value() == "")
        page.screenshot(path=str(SHOTS / "settings-empty-no-env.png"))

        browser.close()

    teardown()

    print("\n== summary")
    for name, ok in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        teardown()
