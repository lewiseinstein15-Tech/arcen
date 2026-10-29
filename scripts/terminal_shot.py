"""Real-terminal screenshots of the actual installed console commands.

The other capture scripts (``capture_demo.py`` …) use Textual's own SVG
export, which is a library render of the widget tree. This script is
different: it spawns the real command (e.g. ``arcen-tui --demo`` or
``ARCEN_TUI=new arcen-tui``) in a real PTY with real termios sizing, feeds
the bytes to a real terminal emulator (xterm.js running in headless
Chromium over a websocket), and screenshots the emulator's pixels.

Reusable for every TUI ticket so each change is evidenced by a genuine
terminal frame rather than a synthetic render::

    python scripts/terminal_shot.py --cols 132 --rows 44 --wait 20 \\
        --out docs/verify/TUI-04-real-demo-wide.png -- arcen-tui --demo

One-time setup on a fresh machine: ``bash scripts/setup_capture.sh`` plus
``pip install playwright && playwright install chromium``.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import pathlib
import threading

from aiohttp import web
from ptyprocess import PtyProcess

REPO = pathlib.Path(__file__).resolve().parents[1]
ASSETS = REPO / "scripts" / "terminal_assets"
FONT = pathlib.Path.home() / ".local" / "share" / "fonts" / "FiraCode-VF.ttf"
# Rootless Debian .deb extraction prefix (see scripts/setup_capture.sh).
_CHROMIUM_LIBS = pathlib.Path.home() / ".local" / "chromium-libs" / "usr" / "lib"
INK = "#0B0E14"


def _browser_env() -> dict[str, str]:
    env = dict(os.environ)
    extra = str(_CHROMIUM_LIBS / "x86_64-linux-gnu")
    if pathlib.Path(extra).exists():
        env["LD_LIBRARY_PATH"] = (
            f"{extra}:{env['LD_LIBRARY_PATH']}" if env.get("LD_LIBRARY_PATH") else extra
        )
    return env

# The child PTY lives in the server thread's event loop.
_child: dict[str, PtyProcess] = {}

# xterm-style byte sequences for the keys --send-at can inject.
KEY_SEQUENCES: dict[str, bytes] = {
    "pageup": b"\x1b[5~",
    "pagedown": b"\x1b[6~",
    "home": b"\x1b[1~",
    "end": b"\x1b[4~",
    "up": b"\x1b[A",
    "down": b"\x1b[B",
    "enter": b"\r",
    "ctrl+c": b"\x03",
    "ctrl+s": b"\x13",
}


def _spawn(argv: list[str], env: dict[str, str], cols: int, rows: int) -> PtyProcess:
    child_env = dict(os.environ)
    child_env.update(env)
    child_env["TERM"] = "xterm-256color"   # terminfo Textual understands
    child_env["COLORTERM"] = "truecolor"  # force hex colors, not 256 palette
    proc = PtyProcess.spawn(argv, dimensions=(rows, cols), env=child_env)
    _child["proc"] = proc
    return proc


async def _ws_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    cols = int(request.query.get("cols", "132"))
    rows = int(request.query.get("rows", "24"))
    argv = request.app["argv"]
    proc = _spawn(argv, request.app["extra_env"], cols, rows)
    loop = asyncio.get_running_loop()

    async def reader() -> None:
        while True:
            try:
                data = await loop.run_in_executor(None, proc.read, 4096)
            except EOFError:
                await ws.close()
                return
            if not data:
                await ws.close()
                return
            await ws.send_bytes(data)

    reader_task = asyncio.create_task(reader())
    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.BINARY:
                proc.write(msg.data)
            elif msg.type == web.WSMsgType.TEXT:
                proc.write(msg.data.encode())
    finally:
        reader_task.cancel()
        try:
            proc.terminate(force=True)
        except ProcessLookupError:
            pass
    return ws


async def _font(_request: web.Request) -> web.Response:
    if not FONT.exists():
        return web.Response(status=404)
    return web.Response(body=FONT.read_bytes(), content_type="font/ttf")


def _index_html(cols: int, rows: int, font_size: int) -> str:
    font_face = (
        "@font-face{font-family:'Fira Code';src:url('/font') format('truetype');}"
        if FONT.exists()
        else "/* Fira Code not installed; falling back to system mono */"
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="/assets/xterm/xterm.css">
<style>
  {font_face}
  html,body {{ margin:0; padding:0; background:{INK}; }}
  #term {{ padding:0; width:fit-content; }}
  .xterm .xterm-viewport {{ overflow:hidden !important; }}
</style></head>
<body><div id="term"></div>
<script src="/assets/xterm/xterm.js"></script>
<script src="/assets/xterm/addon-fit.js"></script>
<script>
  const term = new Terminal({{
    cols: {cols}, rows: {rows},
    fontSize: {font_size},
    fontFamily: "'Fira Code','JetBrains Mono','DejaVu Sans Mono',monospace",
    cursorBlink: true, drawBoldTextInBrightColors: true,
    theme: {{ background: '{INK}', foreground: '#DCE2EE',
             selectionBackground: '#2A3346', cursor: '#A78BFA' }},
  }});
  term.open(document.getElementById('term'));
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${{proto}}://${{location.host}}/ws?cols={cols}&rows={rows}`);
  ws.binaryType = 'arraybuffer';
  ws.onmessage = (ev) => term.write(new Uint8Array(ev.data));
  term.onData((d) => ws.send(d));
  // Inject a key sequence (base64 bytes) from the screenshot driver.
  window.__send = (b64) => ws.send(
      Uint8Array.from(atob(b64), (c) => c.charCodeAt(0)));
  window.__ready = true;
</script></body></html>"""


async def _index(request: web.Request) -> web.Response:
    cols = int(request.query.get("cols", "132"))
    rows = int(request.query.get("rows", "24"))
    font_size = int(request.query.get("fs", "15"))
    return web.Response(text=_index_html(cols, rows, font_size), content_type="text/html")


def _start_server(argv: list[str], extra_env: dict[str, str]) -> tuple[web.AppRunner, str]:
    app = web.Application()
    app["argv"] = argv
    app["extra_env"] = extra_env
    app.router.add_get("/", _index)
    app.router.add_get("/font", _font)
    app.router.add_get("/ws", _ws_handler)
    app.router.add_static("/assets", ASSETS)

    runner = web.AppRunner(app, access_log=None)
    loop = asyncio.new_event_loop()

    def serve() -> None:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(runner.setup())
        site = web.TCPSite(runner, "127.0.0.1", 0)
        loop.run_until_complete(site.start())
        loop.run_forever()

    threading.Thread(target=serve, daemon=True).start()
    future = asyncio.run_coroutine_threadsafe(_wait_port(runner), loop)
    port = future.result(timeout=5)
    return runner, f"http://127.0.0.1:{port}"


async def _wait_port(runner: web.AppRunner) -> int:
    for _ in range(50):
        if runner.addresses:
            return runner.addresses[0][1]
        await asyncio.sleep(0.05)
    raise RuntimeError("test server never bound a port")


def shoot(
    argv: list[str],
    out: pathlib.Path,
    cols: int,
    rows: int,
    wait: float,
    font_size: int,
    scale: int,
    extra_env: dict[str, str],
    sends: list[tuple[float, str]] | None = None,
) -> None:
    import base64

    from playwright.sync_api import sync_playwright

    _runner, url = _start_server(argv, extra_env)
    out.parent.mkdir(parents=True, exist_ok=True)
    sends = sorted(sends or [])
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, env=_browser_env())
            page = browser.new_page(
                viewport={"width": 2000, "height": 1400},
                device_scale_factor=scale,
            )
            page.goto(f"{url}/?cols={cols}&rows={rows}&fs={font_size}")
            page.wait_for_function("window.__ready === true")
            elapsed = 0.0
            for at_seconds, key in sends:
                delay = max(0.0, at_seconds - elapsed)
                page.wait_for_timeout(int(delay * 1000))
                elapsed += delay
                sequence = KEY_SEQUENCES[key]
                page.evaluate("([b]) => window.__send(b)", [base64.b64encode(sequence).decode()])
            remaining = max(0.0, wait - elapsed)
            page.wait_for_timeout(int(remaining * 1000))
            page.locator("#term").screenshot(path=str(out))
            browser.close()
    finally:
        proc = _child.get("proc")
        if proc is not None and proc.isalive():
            proc.terminate(force=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cols", type=int, default=132)
    parser.add_argument("--rows", type=int, default=44)
    parser.add_argument("--wait", type=float, default=20.0,
                        help="seconds to let the app run before capture")
    parser.add_argument("--font-size", type=int, default=15)
    parser.add_argument("--scale", type=int, default=2,
                        help="device pixel ratio (2 = Retina-sharp)")
    parser.add_argument("--env", action="append", default=[],
                        help="extra env var KEY=VAL, repeatable")
    parser.add_argument("--send-at", action="append", default=[], metavar="SEC:KEY",
                        help=f"inject a key at SEC seconds, repeatable; "
                             f"keys: {', '.join(KEY_SEQUENCES)}")
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER,
                        help="-- <command> [args…]")
    args = parser.parse_args()

    argv = args.command[1:] if args.command and args.command[0] == "--" else args.command
    if not argv:
        parser.error("provide a command after --")
    extra_env = {}
    for pair in args.env:
        key, _, value = pair.partition("=")
        extra_env[key] = value

    sends: list[tuple[float, str]] = []
    for spec in args.send_at:
        at, _, key = spec.partition(":")
        if not at or key not in KEY_SEQUENCES:
            parser.error(f"--send-at expects SEC:KEY with key in {sorted(KEY_SEQUENCES)}")
        sends.append((float(at), key))

    shoot(argv, args.out, args.cols, args.rows, args.wait,
          args.font_size, args.scale, extra_env, sends)
    print(f"wrote {args.out.relative_to(REPO) if args.out.is_relative_to(REPO) else args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
