"""Console router; inspection commands do not boot the server or plugins."""

from __future__ import annotations

import json
import sys

USAGE = "usage: arcen [--version | serve | run GOAL --json | resume SESSION | apply SESSION | harness ...]"


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("arcen")
    except PackageNotFoundError:
        return "0.1.0"


def _session_dir() -> str:
    """Resolve the configured session directory without triggering config writes."""
    import yaml

    from arcen.config import ArcenConfig, default_config_path

    path = default_config_path()
    if path.exists():
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict) and isinstance(loaded.get("session"), dict):
                directory = loaded["session"].get("dir")
                if isinstance(directory, str) and directory.strip():
                    return directory
        except (OSError, yaml.YAMLError):
            pass
    return ArcenConfig().session.dir


def _resolve_session(store, ref: str) -> str | None:
    """Accept a session uuid or a run id; return the owning session id."""
    import uuid as uuidlib

    try:
        session_id = str(uuidlib.UUID(ref))
    except ValueError:
        session_id = None
    if session_id is not None:
        return session_id if store.exists(session_id) else None
    if not ref.replace("-", "").replace("_", "").isalnum():
        return None
    for path in sorted(store.directory.glob("*.jsonl")):
        for event in store.read(path.stem):
            if event.get("run_id") == ref:
                return path.stem
    return None


def _resume(args: list[str]) -> int:
    import argparse

    from arcen.session.store import SessionStore

    parser = argparse.ArgumentParser(prog="arcen resume")
    parser.add_argument("session", nargs="?", help="session id or run id")
    parser.add_argument("--after", type=int, default=0, help="replay events with seq > N")
    parser.add_argument("--list", action="store_true", help="list known sessions and exit")
    parsed = parser.parse_args(args)
    store = SessionStore(_session_dir())
    if parsed.list:
        for path in sorted(store.directory.glob("*.jsonl")):
            events = store.read(path.stem)
            created = events[0].get("ts") if events else None
            print(f"{path.stem}  events={len(events)}  created={created}")
        return 0
    if not parsed.session:
        parser.error("a session id or run id is required")
    session_id = _resolve_session(store, parsed.session)
    if session_id is None:
        print(f"arcen resume: no session or run {parsed.session!r} found", file=sys.stderr)
        return 1
    for event in store.read(session_id):
        if event.get("seq", 0) > parsed.after:
            print(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
    return 0


def main() -> int | None:
    args = sys.argv[1:]
    if args in (["--version"], ["-V"], ["version"]):
        print(f"arcen {_version()}")
        return 0
    if args and args[0] == "resume":
        return _resume(args[1:])
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
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
