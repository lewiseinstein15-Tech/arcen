"""Fake registry exercises scorer transport; no Docker or benchmark result."""

import base64
import shlex

import pytest

from arcen.config import ArcenConfig
from bench.local_scorer import LocalDockerScorer

PATCH = b"diff --git a/solution.py b/solution.py\nindex 1234567..abcdef0 100644\n--- a/solution.py\n+++ b/solution.py\n@@ -1 +1 @@\n-old\n+new\n"


class FakeRegistry:
    def __init__(self, config, *, workspace):
        from pathlib import Path

        self.files = {p.name: p.read_text() for p in Path(workspace).iterdir()}
        self.closed = False
        self.envelope = {"ok": True, "result": {"exit": 0}}
        self.calls = []

    def dispatch(self, name, args):
        self.calls.append((name, args))
        return self.envelope

    def close(self, *, strict):
        assert strict
        self.closed = True


def test_scorer_uses_fake_sandbox_and_exact_patch_bytes():
    instances = []

    def factory(*args, **kwargs):
        instance = FakeRegistry(*args, **kwargs)
        instances.append(instance)
        return instance

    scorer = LocalDockerScorer(ArcenConfig(), registry_factory=factory)
    assert scorer.score("local-sum-positive", PATCH) is True
    fake = instances[0]
    assert set(fake.files) == {"solution.py", "test_solution.py"}
    assert fake.calls[0][0] == "bash"
    args = shlex.split(fake.calls[0][1]["cmd"])
    assert args[:3] == ["python", "-I", "-c"]
    assert base64.b64decode(args[-1], validate=True) == PATCH
    assert fake.closed


@pytest.mark.parametrize("code,expected", [(0, True), (10, False), (20, False), (124, None)])
def test_scorer_distinguishes_failure_and_unknown(code, expected):
    def factory(*args, **kwargs):
        fake = FakeRegistry(*args, **kwargs)
        fake.envelope = {"ok": code == 0, "result": {"exit": code}, "error": "fake error"}
        return fake

    assert (
        LocalDockerScorer(ArcenConfig(), registry_factory=factory).score(
            "local-sum-positive", PATCH
        )
        is expected
    )


def test_test_file_cannot_be_modified():
    bad = PATCH.replace(b"solution.py", b"test_solution.py")
    with pytest.raises(ValueError, match="only solution.py"):
        LocalDockerScorer(ArcenConfig()).score("local-sum-positive", bad)


def test_bench_cli_help_runs_without_docker():
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "bench.py"
    result = subprocess.run(
        [sys.executable, str(script), "--help"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    assert "--local-task" in result.stdout


def test_trusted_fixture_program_detects_fixed_and_broken_code(tmp_path):
    # Trusted hand-authored fixture code only; no container output is executed.
    import subprocess
    import sys

    from bench.local_bank import load_tasks
    from bench.local_scorer import _PROGRAM

    task = load_tasks()[0]
    for name, content in task["files"].items():
        (tmp_path / name).write_text(content)
    patch = (
        b"diff --git a/solution.py b/solution.py\n"
        b"--- a/solution.py\n+++ b/solution.py\n@@ -1,2 +1,2 @@\n"
        b" def solve(xs):\n-    return sum(xs)\n+    return sum(x for x in xs if x > 0)\n"
    )
    encoded = base64.b64encode(patch).decode()
    result = subprocess.run(
        [sys.executable, "-I", "-c", _PROGRAM, encoded],
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
