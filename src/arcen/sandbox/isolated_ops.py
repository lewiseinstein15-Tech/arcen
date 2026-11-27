"""Isolated file operations executed inside the turn container.

The helper below runs as ``python3 -c`` inside the disposable container, never
on the host. It receives an explicit root (always ``/workspace`` from the
runtime) and refuses any path that resolves outside it. Output is a single JSON
object; the host treats it as untrusted and re-validates the shape.

The ported tools are the read-mostly ones plus whole-file ``file.write`` and
exact-string ``file.edit``. Anything else stays denied by the allowlist and
never falls back to a host registry.
"""

from __future__ import annotations

import json

ALLOWED = (
    "bash",
    "file.read",
    "file.write",
    "file.list",
    "file.glob",
    "search.text",
    "file.edit",
)

MAX_ARG_BYTES = 1_048_576
MAX_READ_BYTES = 2_000_000
# Tool arguments travel as one argv element, and Linux caps a single argument
# at 128 KiB, so a whole-file write is bounded well below that.
MAX_WRITE_BYTES = 96_000
MAX_ENTRIES = 1000
MAX_MATCHES = 500

HELPER = r"""
import fnmatch, json, os, re, sys

op, root, raw = sys.argv[1], os.path.realpath(sys.argv[2]), sys.argv[3]
args = json.loads(raw)
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}


def resolve(path, must_exist=False):
    p = path if os.path.isabs(path) else os.path.join(root, path)
    p = os.path.realpath(p)
    if p != root and not p.startswith(root + os.sep):
        raise ValueError("path escapes the isolated workspace")
    if must_exist and not os.path.exists(p):
        raise ValueError("no such file or directory")
    return p


def read(a):
    p = resolve(a.get("path", ""), must_exist=True)
    if not os.path.isfile(p):
        raise ValueError("not a regular file")
    with open(p, "rb") as fh:
        raw = fh.read(2000001)
    if len(raw) > 2000000:
        raise ValueError("file larger than 2000000 bytes; read a slice instead")
    lines = raw.decode("utf-8", errors="replace").splitlines(keepends=True)
    offset = max(int(a.get("offset_line", 0)), 0)
    limit = min(max(int(a.get("limit_lines", 2000)), 1), 2000)
    return {
        "path": p,
        "total_lines": len(lines),
        "content": "".join(lines[offset:offset + limit]),
        "truncated": len(lines) > offset + limit,
    }


def list_dir(a):
    p = resolve(a.get("path", "."), must_exist=True)
    if not os.path.isdir(p):
        raise ValueError("not a directory")
    entries = []
    for name in sorted(os.listdir(p))[:1000]:
        full = os.path.join(p, name)
        kind = "dir" if os.path.isdir(full) else "file" if os.path.isfile(full) else "other"
        size = os.path.getsize(full) if kind == "file" else 0
        entries.append({"name": name, "type": kind, "size": size})
    return {"path": p, "entries": entries, "truncated": len(os.listdir(p)) > 1000}


def glob_files(a):
    import glob as globmod
    root_dir = resolve(a.get("root", "."), must_exist=True)
    pattern = a.get("pattern", "*")
    matches = []
    for hit in globmod.glob(os.path.join(root_dir, pattern), recursive=True):
        p = os.path.realpath(hit)
        if p == root or p.startswith(root + os.sep):
            matches.append(p)
        if len(matches) >= 500:
            break
    return {"pattern": pattern, "matches": sorted(matches), "truncated": len(matches) >= 500}


def search(a):
    rx = re.compile(a.get("pattern", ""))
    root_dir = resolve(a.get("root", "."), must_exist=True)
    name_glob = a.get("glob", "*")
    limit = min(max(int(a.get("limit", 200)), 1), 500)
    matches = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for fname in sorted(filenames):
            if not fnmatch.fnmatch(fname, name_glob):
                continue
            full = os.path.join(dirpath, fname)
            try:
                with open(full, "r", encoding="utf-8", errors="ignore") as fh:
                    for lineno, line in enumerate(fh, 1):
                        if rx.search(line):
                            matches.append({"path": full, "line": lineno, "text": line.rstrip()[:300]})
                            if len(matches) >= limit:
                                return {"matches": matches, "count": len(matches), "truncated": True}
            except OSError:
                continue
    return {"matches": matches, "count": len(matches), "truncated": False}


def drop_bytecode(p):
    # A same-second, same-size rewrite leaves the old .pyc looking valid to
    # CPython's (mtime, size) check, so the next run would import stale code.
    if not p.endswith(".py"):
        return
    cache = os.path.join(os.path.dirname(p), "__pycache__")
    stem = os.path.splitext(os.path.basename(p))[0]
    try:
        for name in os.listdir(cache):
            if name.startswith(stem + ".") and name.endswith(".pyc"):
                os.unlink(os.path.join(cache, name))
    except OSError:
        pass


def write(a):
    p = resolve(a.get("path", ""))
    if os.path.isdir(p):
        raise ValueError("not a regular file")
    content = a.get("content", "")
    if len(content.encode("utf-8")) > 96000:
        raise ValueError("content larger than 96000 bytes")
    parent = os.path.dirname(p) or root
    os.makedirs(parent, exist_ok=True)
    tmp = p + ".arcen-tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(content)
    os.replace(tmp, p)
    drop_bytecode(p)
    return {"path": p, "bytes": len(content.encode("utf-8"))}


def edit(a):
    p = resolve(a.get("path", ""), must_exist=True)
    if not os.path.isfile(p):
        raise ValueError("not a regular file")
    find = a.get("find", "")
    if not find:
        raise ValueError("find must be a non-empty string")
    replace = a.get("replace", "")
    count = int(a.get("count", -1))
    with open(p, "r", encoding="utf-8") as fh:
        content = fh.read()
    occurrences = content.count(find)
    if occurrences == 0:
        raise ValueError("needle not found in " + p)
    if count >= 0 and occurrences > count:
        raise ValueError("needle is ambiguous: %d occurrences, count=%d" % (occurrences, count))
    updated = content.replace(find, replace) if count < 0 else content.replace(find, replace, count)
    tmp = p + ".arcen-tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(updated)
    os.replace(tmp, p)
    drop_bytecode(p)
    return {
        "path": p,
        "replacements": occurrences if count < 0 else min(count, occurrences),
    }


OPS = {"file.read": read, "file.write": write, "file.list": list_dir,
       "file.glob": glob_files, "search.text": search, "file.edit": edit}

try:
    if op not in OPS:
        raise ValueError("unsupported isolated tool")
    result = {"ok": True, "result": OPS[op](args), "error": None}
except Exception as exc:
    result = {"ok": False, "result": None, "error": str(exc)}
print(json.dumps(result))
"""

_ARG_KEYS = {
    "file.read": {"path", "offset_line", "limit_lines"},
    "file.write": {"path", "content"},
    "file.list": {"path"},
    "file.glob": {"pattern", "root"},
    "search.text": {"pattern", "root", "glob", "limit"},
    "file.edit": {"path", "find", "replace", "count"},
}


def validate(name: str, args: object) -> dict:
    """Reject malformed arguments on the host before anything enters Docker."""
    if name not in _ARG_KEYS:
        raise ValueError(f"tool {name!r} is not an isolated file operation")
    if type(args) is not dict:
        raise ValueError("tool arguments must be an object")
    unknown = set(args) - _ARG_KEYS[name]
    if unknown:
        raise ValueError(f"unknown argument(s): {', '.join(sorted(unknown))}")
    for key in ("path", "root", "pattern", "glob", "find", "replace", "content"):
        if key in args and type(args[key]) is not str:
            raise ValueError(f"{key} must be a string")
    for key in ("offset_line", "limit_lines", "limit", "count"):
        if key in args and type(args[key]) is not int:
            raise ValueError(f"{key} must be an integer")
    if name == "file.write" and len(args.get("content", "").encode("utf-8")) > MAX_WRITE_BYTES:
        raise ValueError("content is too large to write")
    payload = json.dumps(args, ensure_ascii=False)
    if len(payload.encode("utf-8")) > MAX_ARG_BYTES:
        raise ValueError("tool arguments are too large")
    return args


def build_argv(name: str, args: dict, root: str = "/workspace") -> list[str]:
    """argv for ``docker exec`` — a fixed python entrypoint, no shell involved."""
    validate(name, args)
    return ["python3", "-c", HELPER, name, root, json.dumps(args, ensure_ascii=False)]
