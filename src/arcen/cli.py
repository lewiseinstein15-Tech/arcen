"""Console router; inspection commands do not boot the server or plugins."""

from __future__ import annotations

import sys


def main() -> int | None:
    args = sys.argv[1:]
    if args and args[0] == "harness":
        from arcen.harness.cli import main as harness_main

        return harness_main(args[1:])
    if args and args[0] == "run":
        from arcen.headless import main as headless_main

        return headless_main(args[1:])
    if not args or args == ["serve"]:
        from arcen.server.app import main as server_main

        return server_main()
    print("usage: arcen [serve | run GOAL --json | harness ...]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
