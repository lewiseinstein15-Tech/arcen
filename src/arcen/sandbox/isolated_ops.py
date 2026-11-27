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
import fnmatch, json, os, re, subprocess, sys

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


GIT_OUTPUT_LIMIT = 60000
GIT_TIMEOUT = 60
_REF = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._/@{}^~:-]{0,200}\Z")
_SAFE_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_ASKPASS": "/bin/true",
    "GIT_PAGER": "cat",
    "PAGER": "cat",
    "HOME": "/tmp",
}


def git_path(p):
    # A repo-relative path: no absolute, no traversal, no option-looking name.
    if not isinstance(p, str) or not p or p.startswith("/") or p.startswith("-"):
        raise ValueError("invalid repository path")
    if ".." in p.split("/") or "\x00" in p:
        raise ValueError("path escapes the repository")
    return p


def git_ref(ref):
    if not isinstance(ref, str) or not _REF.match(ref) or ".." in ref:
        raise ValueError("invalid git ref")
    return ref


def git_tree(a):
    # `root` is the repo's working tree; the host schema advertises it, so the
    # sandbox must honour it rather than reject it as an unknown argument.
    want = a.get("root")
    if not want:
        return root
    p = resolve(want, must_exist=True)
    if not os.path.isdir(p):
        raise ValueError("root must be a directory")
    return p


def git_run(argv, stdin=None, cwd=None):
    # Run git inside the workspace. Non-zero exits become tool errors.
    env = dict(os.environ)
    env.update(_SAFE_ENV)
    proc = subprocess.run(
        ["git", "-C", cwd or root, "-c", "safe.directory=*",
         "-c", "user.name=ARCEN", "-c", "user.email=arcen@localhost"] + argv,
        input=stdin, capture_output=True, text=True, timeout=GIT_TIMEOUT, env=env,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise ValueError(detail[-1][:500] if detail else "git failed")
    return proc.stdout


def git_status(a):
    out = git_run(["status", "--porcelain=v1", "--branch"], cwd=git_tree(a))
    branch, ahead, behind, staged, unstaged, untracked = "", 0, 0, [], [], []
    for line in out.splitlines():
        if line.startswith("## "):
            head = line[3:]
            branch = head.split("...")[0].split(" ")[0]
            for token in head.split():
                if token.startswith("ahead "):
                    ahead = int(token[6:].strip(",") or 0)
                elif token.startswith("behind "):
                    behind = int(token[7:].strip(",") or 0)
            continue
        code, path = line[:2], line[3:]
        if code == "??":
            untracked.append(path)
        else:
            (staged if code[0] not in " ?" else unstaged).append({"code": code, "path": path})
    return {"branch": branch, "ahead": ahead, "behind": behind, "staged": staged,
            "unstaged": unstaged, "untracked": untracked,
            "clean": not (staged or unstaged or untracked)}


def git_diff(a):
    tree = git_tree(a)
    argv = ["diff", "--no-color"]
    if a.get("staged"):
        argv.append("--staged")
    if a.get("ref"):
        argv.append(git_ref(a["ref"]))
    if a.get("path"):
        argv += ["--", git_path(a["path"])]
    out = git_run(argv, cwd=tree)
    return {"diff": out[:GIT_OUTPUT_LIMIT], "bytes": len(out), "truncated": len(out) > GIT_OUTPUT_LIMIT}


def git_log(a):
    tree = git_tree(a)
    limit = min(max(int(a.get("limit", 20)), 1), 200)
    argv = ["log", "--no-color", "--date=short",
            "--format=%H%x1f%an%x1f%ad%x1f%s", "-n", str(limit)]
    if a.get("path"):
        argv += ["--", git_path(a["path"])]
    commits = []
    for line in git_run(argv, cwd=tree).splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            commits.append({"hash": parts[0], "author": parts[1], "date": parts[2], "subject": parts[3]})
    return {"commits": commits, "count": len(commits)}


def git_show(a):
    tree = git_tree(a)
    ref = git_ref(a.get("ref") or "HEAD")
    target = ref + (":" + git_path(a["path"]) if a.get("path") else "")
    out = git_run(["show", "--no-color", target], cwd=tree)
    return {"ref": ref, "content": out[:GIT_OUTPUT_LIMIT], "bytes": len(out),
            "truncated": len(out) > GIT_OUTPUT_LIMIT}


def git_add(a):
    tree = git_tree(a)
    paths = a.get("paths") or []
    if not isinstance(paths, list) or not paths or len(paths) > 200:
        raise ValueError("paths must be a non-empty list of at most 200 entries")
    git_run(["add", "--"] + [git_path(p) for p in paths], cwd=tree)
    return {"added": list(paths), "status": git_status({"root": tree})}


def git_commit(a):
    tree = git_tree(a)
    message = (a.get("message") or "").strip()
    if not message:
        raise ValueError("commit message must not be empty")
    argv = ["commit", "-m", message[:2000]]
    if a.get("all"):
        argv.append("--all")
    git_run(argv, cwd=tree)
    head = git_run(["log", "-1", "--format=%H%x1f%s"], cwd=tree).strip().split("\x1f")
    return {"hash": head[0] if head else "", "summary": head[1] if len(head) > 1 else "",
            "status": git_status({"root": tree})}


def git_branch(a):
    tree = git_tree(a)
    if a.get("name") and a.get("create"):
        git_run(["checkout", "-b", git_ref(a["name"])], cwd=tree)
    elif a.get("name"):
        git_run(["branch", git_ref(a["name"])], cwd=tree)
    out = git_run(["branch", "--format=%(refname:short)%09%(HEAD)"], cwd=tree)
    branches = [{"name": line.split("\t")[0], "current": line.endswith("*")}
                for line in out.splitlines() if line.strip()]
    return {"branches": branches, "current": next((b["name"] for b in branches if b["current"]), "")}


def git_checkout(a):
    tree = git_tree(a)
    ref = git_ref(a.get("ref") or "")
    if a.get("create"):
        git_run(["checkout", "-b", ref], cwd=tree)
    else:
        git_run(["checkout", ref], cwd=tree)
    return {"current": git_run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=tree).strip()}


def patch_apply(a):
    patch = a.get("patch") or ""
    if not isinstance(patch, str) or not patch.strip():
        raise ValueError("patch must be a non-empty unified diff")
    if len(patch.encode("utf-8")) > 400000:
        raise ValueError("patch larger than 400000 bytes")
    argv = ["apply", "--whitespace=nowarn"]
    if a.get("reverse"):
        argv.append("--reverse")
    if a.get("check"):
        argv.append("--check")
    git_run(argv + ["-"], stdin=patch)
    touched = sorted({line.split("+++ b/")[-1].strip() for line in patch.splitlines()
                      if line.startswith("+++ b/")})
    return {"applied": not a.get("check"), "check_only": bool(a.get("check")), "files": touched}


SYMBOL_RE = re.compile(
    r"^\s*(?:async\s+)?(?:def|class|function|func|fn|interface|struct|enum|type|impl|module)\s+([A-Za-z_][\w]*)"
    r"|^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_][\w]*)\s*=",
    re.MULTILINE,
)
TEXT_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".rb", ".php",
                 ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".kt", ".swift", ".scala", ".sh",
                 ".sql", ".vue", ".svelte", ".md", ".toml", ".yaml", ".yml", ".json"}


def repo_map(a):
    # A ranked skeleton of the tree: which files carry the code.
    start = resolve(a.get("root", "."), must_exist=True)
    max_files = min(max(int(a.get("max_files", 60)), 1), 400)
    include = a.get("include") or "*"
    scanned = 0
    files = []
    for dirpath, dirnames, filenames in os.walk(start):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for fname in sorted(filenames):
            if not fnmatch.fnmatch(fname, include):
                continue
            full = os.path.join(dirpath, fname)
            if os.path.splitext(fname)[1].lower() not in TEXT_SUFFIXES:
                continue
            try:
                if os.path.getsize(full) > 1_000_000:
                    continue
                with open(full, "r", encoding="utf-8", errors="ignore") as fh:
                    text = fh.read()
            except OSError:
                continue
            scanned += 1
            symbols = [m.group(1) or m.group(2) for m in SYMBOL_RE.finditer(text)]
            lines = text.count("\n") + 1
            rel = os.path.relpath(full, root)
            files.append({"path": rel, "lines": lines, "symbols": len(symbols),
                          "top": symbols[:8],
                          "rank": len(symbols) * 3 + min(lines // 20, 20)})
    files.sort(key=lambda f: (-f["rank"], f["path"]))
    return {"files": files[:max_files], "scanned": scanned,
            "truncated": len(files) > max_files, "root": os.path.relpath(start, root)}


OPS = {"file.read": read, "file.write": write, "file.list": list_dir,
       "file.glob": glob_files, "search.text": search, "file.edit": edit,
       "git.status": git_status, "git.diff": git_diff, "git.log": git_log,
       "git.show": git_show, "git.add": git_add, "git.commit": git_commit,
       "git.branch": git_branch, "git.checkout": git_checkout,
       "patch.apply": patch_apply, "repo.map": repo_map}

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
    "git.status": {"root"},
    "git.diff": {"path", "staged", "ref", "root"},
    "git.log": {"limit", "path", "root"},
    "git.show": {"ref", "path", "root"},
    "git.add": {"paths", "root"},
    "git.commit": {"message", "all", "root"},
    "git.branch": {"name", "create", "root"},
    "git.checkout": {"ref", "create", "root"},
    "patch.apply": {"patch", "reverse", "check"},
    "repo.map": {"root", "max_files", "include"},
}

_STR_KEYS = (
    "path",
    "root",
    "pattern",
    "glob",
    "find",
    "replace",
    "content",
    "ref",
    "message",
    "name",
    "patch",
    "include",
)
_INT_KEYS = ("offset_line", "limit_lines", "limit", "count", "max_files")
_BOOL_KEYS = ("staged", "all", "create", "reverse", "check")


def validate(name: str, args: object) -> dict:
    """Reject malformed arguments on the host before anything enters Docker."""
    if name not in _ARG_KEYS:
        raise ValueError(f"tool {name!r} is not an isolated file operation")
    if type(args) is not dict:
        raise ValueError("tool arguments must be an object")
    unknown = set(args) - _ARG_KEYS[name]
    if unknown:
        raise ValueError(f"unknown argument(s): {', '.join(sorted(unknown))}")
    for key in _STR_KEYS:
        if key in args and type(args[key]) is not str:
            raise ValueError(f"{key} must be a string")
    for key in _INT_KEYS:
        if key in args and type(args[key]) is not int:
            raise ValueError(f"{key} must be an integer")
    for key in _BOOL_KEYS:
        if key in args and type(args[key]) is not bool:
            raise ValueError(f"{key} must be a boolean")
    if "paths" in args:
        paths = args["paths"]
        if type(paths) is not list or any(type(item) is not str for item in paths):
            raise ValueError("paths must be a list of strings")
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
