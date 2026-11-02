"""Phase-0 read-only tracked-file and exception inventory; not a safety proof."""

from __future__ import annotations

import argparse
import ast
import collections
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCOPES = ("src/arcen", "tests", "scripts", "ui", "docker", ".github")
DEST = ROOT / "docs/audit"
JS_CATCH = re.compile(r"\bcatch\b|\.catch\s*\(")
SHELL_MASK = re.compile(r"\|\|\s*(?:true|:)|2\s*>\s*/dev/null")


def output():
    raw = subprocess.check_output(["git", "ls-files", "-z", "--", *SCOPES], cwd=ROOT)
    paths = sorted(p.decode("utf-8") for p in raw.split(b"\0") if p)
    inventory, exceptions, nonpython = [], [], []
    summary = collections.Counter()
    for name in paths:
        data = (ROOT / name).read_bytes()  # every tracked file, including binary assets
        category = "src/arcen" if name.startswith("src/arcen/") else name.split("/")[0]
        summary[f"files:{category}"] += 1
        try:
            text = data.decode("utf-8")
            if "\0" in text:
                raise UnicodeError("binary content")
        except UnicodeError:
            inventory.append((name, len(data), "binary", "-", hashlib.sha256(data).hexdigest()))
            summary["binary_files"] += 1
            continue
        inventory.append(
            (name, len(data), "utf-8", len(text.splitlines()), hashlib.sha256(data).hexdigest())
        )
        summary["text_files"] += 1
        if name.endswith(".py"):
            try:
                tree = ast.parse(text, filename=name)
            except SyntaxError as exc:
                summary["python_parse_errors"] += 1
                exceptions.append((name, exc.lineno or 0, "PARSE_ERROR", "", str(exc.msg)))
                continue
            summary["python_parsed"] += 1
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler):
                    summary["python_except_handlers"] += 1
                    kinds = sorted(
                        {
                            type(n).__name__
                            for b in node.body
                            for n in ast.walk(b)
                            if isinstance(
                                n, (ast.Pass, ast.Return, ast.Continue, ast.Break, ast.Raise)
                            )
                        }
                    )
                    caught = ast.unparse(node.type) if node.type else "bare"
                    # Include the full body for review; an absent Raise is not
                    # proof of a swallowed exception (calls may raise or log).
                    body = " | ".join(ast.unparse(b).replace("\n", " ") for b in node.body)
                    exceptions.append((name, node.lineno, caught, ",".join(kinds), body))
                elif isinstance(node, (ast.With, ast.AsyncWith)):
                    for item in node.items:
                        call = item.context_expr
                        if isinstance(call, ast.Call) and (
                            ast.unparse(call.func) in ("suppress", "contextlib.suppress")
                        ):
                            summary["python_suppress_blocks"] += 1
                            exceptions.append(
                                (name, node.lineno, "SUPPRESS", "", ast.unparse(call))
                            )
        elif name.endswith((".ts", ".tsx", ".js")):
            for number, line in enumerate(text.splitlines(), 1):
                if JS_CATCH.search(line):
                    summary["js_catch_lines"] += 1
                    nonpython.append((name, number, "catch-candidate", line.strip()[:240]))
        elif name.endswith((".sh", ".yml", ".yaml")):
            for number, line in enumerate(text.splitlines(), 1):
                if SHELL_MASK.search(line):
                    summary["shell_mask_lines"] += 1
                    nonpython.append((name, number, "suppression-candidate", line.strip()[:240]))
    summary["tracked_files"] = len(paths)

    def tsv(rows):
        return "".join(
            "\t".join(str(v).replace("\t", " ").replace("\n", " ") for v in row) + "\n"
            for row in rows
        )

    return {
        "tracked-files.tsv": "path\tbytes\tformat\tlines\tsha256\n" + tsv(inventory),
        "python-exceptions.tsv": "path\tline\tcaught\tflow-nodes\tbody (static syntax; not a verdict)\n"
        + tsv(sorted(exceptions)),
        "other-catches.tsv": "path\tline\tcategory\tline (candidate only)\n"
        + tsv(sorted(nonpython)),
        "scan-summary.json": json.dumps(dict(sorted(summary.items())), indent=2) + "\n",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    files = output()
    if args.write:
        DEST.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            (DEST / name).write_text(text, encoding="utf-8")
        print("Wrote Phase-0 inventory files.")
    else:
        mismatched = [
            name
            for name, text in files.items()
            if not (DEST / name).exists() or (DEST / name).read_text(encoding="utf-8") != text
        ]
        if mismatched:
            print("Inventory mismatch:", ", ".join(mismatched))
            return 1
        print("Phase-0 inventory matches tracked files.")
    print(files["scan-summary.json"], end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
