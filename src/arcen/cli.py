"""Console router; inspection commands do not boot the server or plugins."""

from __future__ import annotations

import sys


def main() -> int | None:
    args = sys.argv[1:]
    if args and args[0] == "apply":
        import argparse
        from pathlib import Path

        from arcen.sandbox.artifact_apply import apply_artifact
        from arcen.sandbox.patch_validation import ArtifactError

        parser = argparse.ArgumentParser(prog="arcen apply")
        parser.add_argument("session")
        parser.add_argument(
            "--yes", action="store_true", help="apply after checks; default is dry run"
        )
        parser.add_argument("--allow-different-base", action="store_true")
        parsed = parser.parse_args(args[1:])
        try:
            result = apply_artifact(
                parsed.session,
                target=Path.cwd(),
                yes=parsed.yes,
                allow_different_base=parsed.allow_different_base,
            )
        except (ArtifactError, OSError) as exc:
            print(f"arcen apply: {exc}", file=sys.stderr)
            return 1
        for path in result["files"]:
            print(path)
        print("Applied; no commit created." if result["applied"] else "Dry run: no files changed.")
        return 0
    if args and args[0] == "harness":
        from arcen.harness.cli import main as harness_main

        return harness_main(args[1:])
    if args and args[0] == "run":
        from arcen.headless import main as headless_main

        return headless_main(args[1:])
    if not args or args == ["serve"]:
        from arcen.server.app import main as server_main

        return server_main()
    print("usage: arcen [serve | run GOAL --json | apply SESSION | harness ...]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
