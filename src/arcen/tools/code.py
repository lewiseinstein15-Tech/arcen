"""ARCEN — code tools (OpenHands tools/ pattern, wrapped in Part 3).

run a snippet, safe expression eval, format via ast.unparse, outline, diff.
"""

from __future__ import annotations

import ast
import difflib
import operator
import subprocess

from pydantic import BaseModel, Field

from .registry import BaseTool

# safe evaluator: literal ops + whitelisted callables only
_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos, ast.Not: operator.not_}
_CMP = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}
_CALLABLES = {"abs": abs, "min": min, "max": max, "round": round, "len": len, "sum": sum}


class _SafeEval(ast.NodeVisitor):
    """Arithmetic/comparison evaluator over a locked node set — no eval()."""

    def __init__(self, names: dict[str, object]) -> None:
        self.names = names

    def visit_Expression(self, node: ast.Expression) -> object:
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> object:
        if isinstance(node.value, (int, float, bool, str)) and not isinstance(node.value, complex):
            return node.value
        raise ValueError(f"constant type not allowed: {type(node.value).__name__}")

    def visit_Name(self, node: ast.Name) -> object:
        if node.id in self.names:
            return self.names[node.id]
        raise ValueError(f"name not provided: {node.id!r}")

    def visit_BinOp(self, node: ast.BinOp) -> object:
        op = _BINOPS.get(type(node.op))
        if op is None:
            raise ValueError("operator not allowed")
        return op(self.visit(node.left), self.visit(node.right))

    def visit_UnaryOp(self, node: ast.UnaryOp) -> object:
        op = _UNARY.get(type(node.op))
        if op is None:
            raise ValueError("operator not allowed")
        return op(self.visit(node.operand))

    def visit_Compare(self, node: ast.Compare) -> object:
        left = self.visit(node.left)
        for op, right in zip(node.ops, node.comparators):
            fn = _CMP.get(type(op))
            if fn is None or not fn(left, self.visit(right)):
                return False
            left = right
        return True

    def visit_BoolOp(self, node: ast.BoolOp) -> object:
        values = [self.visit(v) for v in node.values]
        return all(values) if isinstance(node.op, ast.And) else any(values)

    def visit_IfExp(self, node: ast.IfExp) -> object:
        return self.visit(node.body) if self.visit(node.test) else self.visit(node.orelse)

    def visit_Call(self, node: ast.Call) -> object:
        if not isinstance(node.func, ast.Name) or node.func.id not in _CALLABLES:
            raise ValueError("only abs/min/max/round/len/sum calls are allowed")
        args = [self.visit(a) for a in node.args]
        return _CALLABLES[node.func.id](*args)

    def generic_visit(self, node: ast.AST) -> object:
        raise ValueError(f"node not allowed: {type(node).__name__}")


def safe_eval(expr: str, names: dict[str, object]) -> object:
    tree = ast.parse(expr, mode="eval")
    return _SafeEval(names).visit(tree)


class CodeRun(BaseTool):
    name = "code.run"
    description = "Run a Python snippet with `python -c`, capture stdout/stderr/exit."
    version = "1.0.0"
    danger = "sandboxed"

    class Args(BaseModel):
        code: str = Field(description="Python source to run")
        timeout_s: float = Field(default=30.0, ge=0.1, le=600.0, description="hard timeout")

    def _run(self, a: "CodeRun.Args") -> dict:
        proc = subprocess.run(
            ["python3", "-c", a.code],
            capture_output=True,
            text=True,
            timeout=a.timeout_s,
        )
        return {"stdout": proc.stdout, "stderr": proc.stderr, "exit": proc.returncode}


class CodeEval(BaseTool):
    name = "code.eval_expr"
    description = "Evaluate a single arithmetic/comparison expression safely (no eval, no imports)."
    version = "1.0.0"
    danger = "safe"

    class Args(BaseModel):
        expr: str = Field(description="e.g. 2 ** 10 == 1024")
        variables: dict[str, float] = Field(default_factory=dict, description="name → number")

    def _run(self, a: "CodeEval.Args") -> dict:
        return {"expr": a.expr, "value": safe_eval(a.expr, dict(a.variables))}


class CodeFormat(BaseTool):
    name = "code.format"
    description = "Normalize Python source formatting via ast.unparse."
    version = "1.0.0"
    danger = "safe"

    class Args(BaseModel):
        source: str = Field(description="Python source")

    def _run(self, a: "CodeFormat.Args") -> dict:
        tree = ast.parse(a.source)
        return {"formatted": ast.unparse(tree)}


class CodeOutline(BaseTool):
    name = "code.outline"
    description = "Outline a Python file: classes, functions, and their line numbers."
    version = "1.0.0"
    danger = "safe"

    class Args(BaseModel):
        path: str = Field(description=".py file path")

    def _run(self, a: "CodeOutline.Args") -> dict:
        with open(a.path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        nodes = []
        for node in tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                nodes.append({"type": type(node).__name__, "name": node.name, "line": node.lineno})
        return {"path": a.path, "symbols": nodes}


class CodeDiff(BaseTool):
    name = "code.diff"
    description = "Unified diff of two texts (or two files)."
    version = "1.0.0"
    danger = "safe"

    class Args(BaseModel):
        before: str | None = Field(default=None, description="text before")
        after: str | None = Field(default=None, description="text after")
        before_path: str | None = Field(default=None, description="file to read as 'before'")
        after_path: str | None = Field(default=None, description="file to read as 'after'")
        from_label: str = Field(default="a", description="diff header label")
        to_label: str = Field(default="b", description="diff header label")

    def _run(self, a: "CodeDiff.Args") -> dict:
        before = a.before if a.before is not None else _read(a.before_path)
        after = a.after if a.after is not None else _read(a.after_path)
        diff = "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=a.from_label,
                tofile=a.to_label,
            )
        )
        return {"diff": diff, "changed": bool(diff)}


def _read(path: str | None) -> str:
    if path is None:
        return ""
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()
