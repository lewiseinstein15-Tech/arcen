import ast

from bench.local_bank import load_tasks


def test_bank_has_twenty_unique_original_tasks_with_parseable_code():
    tasks = load_tasks()
    assert len(tasks) == 20
    assert len({task["id"] for task in tasks}) == 20
    for task in tasks:
        assert task["goal"]
        for content in task["files"].values():
            ast.parse(content)
        assert "self.assert" in task["files"]["test_solution.py"]


def test_each_authored_starting_fixture_fails_its_test(tmp_path):
    # Only this repository's hand-authored fixtures execute here; no container
    # or candidate/agent output is run on the host. This is not a benchmark.
    import subprocess
    import sys

    for task in load_tasks():
        workspace = tmp_path / task["id"]
        workspace.mkdir()
        for name, content in task["files"].items():
            (workspace / name).write_text(content)
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-m",
                "unittest",
                "discover",
                "-s",
                ".",
                "-p",
                "test_solution.py",
            ],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert result.returncode == 1, (task["id"], result.stdout, result.stderr)
        assert "FAILED (" in result.stderr, (task["id"], result.stderr)
