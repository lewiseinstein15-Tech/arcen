"""Read-oriented harness CLI; execution and adoption are not enabled."""

from __future__ import annotations

import argparse
import difflib
import sqlite3
import sys
import unicodedata
from importlib import resources
from pathlib import Path

from .lineage import HarnessLineage
from .manifest import MAX_COMPONENT_BYTES, default_manifest
from .resolver import HarnessError
from .store import HarnessStore


def _existing(root: str) -> tuple[HarnessStore, HarnessLineage]:
    base = Path(root).expanduser()
    for path in (base, base / "objects", base / "objects/sha256"):
        if path.is_symlink() or not path.is_dir():
            raise HarnessError("store is missing or invalid; run harness init first")
    db_path = base / "lineage.sqlite3"
    if db_path.is_symlink() or not db_path.is_file():
        raise HarnessError("store database is missing or invalid; run harness init first")
    store = HarnessStore(base)
    return store, HarnessLineage(store, read_only=True)


def _init(root: str) -> str:
    store = HarnessStore(root)
    manifest = default_manifest()
    package = resources.files("arcen")
    for name, digest in manifest.components.items():
        with package.joinpath(*name.split("/")).open("rb") as stream:
            raw = stream.read(MAX_COMPONENT_BYTES + 1)
        if store.put_blob(raw) != digest:
            raise HarnessError(f"packaged component changed: {name}")
    object_id = store.put_manifest(manifest)
    HarnessLineage(store).initialize_baseline(object_id)
    return object_id


def _doctor(root: str) -> dict[str, int]:
    store, db = _existing(root)
    result = db.audit()
    objects = list(store.objects.iterdir())
    for item in objects:
        # A stale/foreign file, symlink, or corrupt object is an error.
        store.get_blob(item.name)
    result["objects"] = len(objects)
    return result


def _safe(text: str) -> str:
    # A stored candidate is untrusted display data: do not execute ANSI or
    # bidirectional terminal controls while showing a diff.
    return "".join(
        char if char in "\n\t" or unicodedata.category(char) not in {"Cc", "Cf"} else "�"
        for char in text
    )


def _diff(root: str, ref: str) -> str:
    store, db = _existing(root)
    baseline = store.get_manifest(db.resolve("refs/heads/adopted"))
    candidate = store.get_manifest(db.resolve(ref))
    output = []
    if baseline.model_pin != candidate.model_pin:
        output.append(f"model pin: {_safe(baseline.model_pin)} -> {_safe(candidate.model_pin)}\n")
    for name in sorted(baseline.components):
        old_hash, new_hash = baseline.components[name], candidate.components[name]
        if old_hash == new_hash:
            continue
        try:
            old = _safe(store.get_blob(old_hash).decode("utf-8")).splitlines(keepends=True)
            new = _safe(store.get_blob(new_hash).decode("utf-8")).splitlines(keepends=True)
        except UnicodeDecodeError as exc:
            raise HarnessError(f"non-UTF-8 component: {name}") from exc
        output.extend(
            difflib.unified_diff(old, new, fromfile=f"baseline/{name}", tofile=f"candidate/{name}")
        )
        if sum(len(x) for x in output) > MAX_COMPONENT_BYTES:
            raise HarnessError("diff exceeds display limit")
    return "".join(output) if output else "No differences.\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arcen harness")
    parser.add_argument("--store", default="~/.arcen/harness", help="trusted local store directory")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="initialize packaged baseline metadata")
    commands.add_parser("doctor", help="verify stored objects, refs and lineage")
    diff = commands.add_parser("diff", help="compare a candidate to baseline")
    diff.add_argument("ref", help="candidate ref, e.g. refs/candidates/example")
    rollback = commands.add_parser("rollback", help="unavailable until adoption gates exist")
    rollback.add_argument("ref", help="target ref (not applied yet)")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            print(f"Initialized packaged baseline: {_init(args.store)}")
            print("Metadata only; candidate selection and adoption remain disabled.")
        elif args.command == "doctor":
            stats = _doctor(args.store)
            print(
                "Store integrity OK: " + ", ".join(f"{key}={value}" for key, value in stats.items())
            )
            print("Hashes do not authenticate provenance; candidate selection remains disabled.")
        elif args.command == "diff":
            print(_diff(args.store, args.ref), end="")
        else:
            raise HarnessError(
                "rollback unavailable: no adoption/approval safety gate is implemented"
            )
    except (HarnessError, OSError, sqlite3.Error) as exc:
        print(f"harness: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
