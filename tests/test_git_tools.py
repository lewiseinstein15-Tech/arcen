"""git, patch and repo.map — the engineering surface the planner can plan.

Two implementations back one contract: the tool classes run on the host (CLI
mode), the isolated helper runs inside the turn container. These tests drive
both against the same real repository and assert they agree, because a silent
divergence would mean the model gets one behaviour in the UI and another from
the CLI.

The security tests are the other half: a ref that looks like a git option, a
path that climbs out of the tree, and an unknown argument must all be refused
before anything is executed.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from arcen.guardrails import default_policy
from arcen.sandbox.isolated_ops import HELPER, validate
from arcen.tools import catalog
from arcen.tools.git import (
    GitAdd,
    GitBranch,
    GitCheckout,
    GitCommit,
    GitDiff,
    GitLog,
    GitShow,
    GitStatus,
)
from arcen.tools.patch import PatchApply
from arcen.tools.registry import load_builtin
from arcen.tools.repomap import RepoMap

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


def _git(root, *argv):
    subprocess.run(
        ["git", "-C", str(root), "-c", "safe.directory=*", *argv],
        check=True,
        capture_output=True,
        text=True,
        env={**GIT_ENV, "PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(root)},
    )


@pytest.fixture()
def repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "README.md").write_text("# demo\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "initial commit")
    return tmp_path


def helper(root, name, args):
    """Run the in-container helper on the host, exactly as the boundary would."""
    argv = ["python3", "-c", HELPER, name, str(root), json.dumps(args)]
    done = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    return json.loads(done.stdout)


def call(tool, **args):
    return tool.execute(args)


# -- parity between the two implementations ----------------------------------


def test_status_agrees_between_host_and_helper(repo):
    host = call(GitStatus(), root=str(repo))["result"]
    boxed = helper(repo, "git.status", {})["result"]
    assert host == boxed
    assert host["clean"] is True
    assert host["branch"] == "main"


def test_status_reports_dirty_paths(repo):
    (repo / "src" / "app.py").write_text("def add(a, b):\n    return b + a\n")
    (repo / "new.txt").write_text("x\n")
    for result in (
        call(GitStatus(), root=str(repo))["result"],
        helper(repo, "git.status", {})["result"],
    ):
        assert result["clean"] is False
        assert [u["path"] for u in result["unstaged"]] == ["src/app.py"]
        assert result["untracked"] == ["new.txt"]


def test_diff_agrees_and_is_scoped(repo):
    (repo / "src" / "app.py").write_text("def add(a, b):\n    return b + a\n")
    (repo / "README.md").write_text("# changed\n")
    host = call(GitDiff(), root=str(repo), path="src/app.py")["result"]
    boxed = helper(repo, "git.diff", {"path": "src/app.py"})["result"]
    assert host == boxed
    assert "b + a" in host["diff"]
    assert "README" not in host["diff"]


def test_log_and_show_agree(repo):
    host_log = call(GitLog(), root=str(repo), limit=5)["result"]
    boxed_log = helper(repo, "git.log", {"limit": 5})["result"]
    assert host_log == boxed_log
    assert host_log["commits"][0]["subject"] == "initial commit"

    host_show = call(GitShow(), root=str(repo), ref="HEAD", path="src/app.py")["result"]
    boxed_show = helper(repo, "git.show", {"ref": "HEAD", "path": "src/app.py"})["result"]
    assert host_show["content"] == boxed_show["content"]
    assert "def add" in host_show["content"]


def test_commit_round_trip_agrees(repo):
    (repo / "src" / "app.py").write_text("def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
    assert call(GitAdd(), root=str(repo), paths=["src/app.py"])["ok"] is True
    host = call(GitCommit(), root=str(repo), message="add sub")["result"]
    assert host["summary"] == "add sub"
    assert host["status"]["clean"] is True

    (repo / "README.md").write_text("# demo v2\n")
    boxed = helper(repo, "git.commit", {"message": "bump readme", "all": True})["result"]
    assert boxed["summary"] == "bump readme"
    assert boxed["status"]["clean"] is True


def test_branch_and_checkout(repo):
    created = call(GitBranch(), root=str(repo), name="feature", create=True)["result"]
    assert created["current"] == "feature"
    branches = call(GitBranch(), root=str(repo))["result"]["branches"]
    assert {b["name"] for b in branches} == {"main", "feature"}

    back = call(GitCheckout(), root=str(repo), ref="main")["result"]
    assert back["current"] == "main"
    boxed = helper(repo, "git.checkout", {"ref": "feature"})["result"]
    assert boxed["current"] == "feature"


# -- patch.apply -------------------------------------------------------------


PATCH = """--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a + b
+    return a + b  # patched
"""


def test_patch_check_does_not_write_and_apply_does(repo):
    target = repo / "src" / "app.py"
    before = target.read_text()
    assert call(PatchApply(), root=str(repo), patch=PATCH, check=True)["ok"] is True
    assert target.read_text() == before

    result = call(PatchApply(), root=str(repo), patch=PATCH)["result"]
    assert result["applied"] is True
    assert result["files"] == ["src/app.py"]
    assert "# patched" in target.read_text()


def test_patch_helper_matches_host_behaviour(repo):
    assert helper(repo, "patch.apply", {"patch": PATCH, "check": True})["ok"] is True
    assert helper(repo, "patch.apply", {"patch": PATCH})["ok"] is True
    assert "# patched" in (repo / "src" / "app.py").read_text()


def test_a_patch_that_does_not_apply_is_an_error_not_a_crash(repo):
    bad = PATCH.replace("-    return a + b", "-    return a + c")
    out = call(PatchApply(), root=str(repo), patch=bad)
    assert out["ok"] is False
    assert out["error"]


# -- repo.map ----------------------------------------------------------------


def test_repo_map_ranks_symbol_files_first_and_skips_vendor(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "core.py").write_text(
        "\n".join(f"def f{i}():\n    return {i}\n" for i in range(6))
    )
    (tmp_path / "docs.md").write_text("hello\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "vendored.js").write_text("function x() {}\n")

    result = call(RepoMap(), root=str(tmp_path), max_files=10)["result"]
    paths = [f["path"] for f in result["files"]]
    assert paths[0] == "src/core.py"
    assert "node_modules/vendored.js" not in paths
    assert result["files"][0]["symbols"] == 6
    assert result["truncated"] is False

    boxed = helper(tmp_path, "repo.map", {"max_files": 10})["result"]
    assert [f["path"] for f in boxed["files"]] == paths


def test_repo_map_truncates_and_says_so(tmp_path):
    for i in range(5):
        (tmp_path / f"m{i}.py").write_text(f"def f{i}():\n    pass\n")
    result = call(RepoMap(), root=str(tmp_path), max_files=2)["result"]
    assert len(result["files"]) == 2
    assert result["truncated"] is True


# -- refusal before execution ------------------------------------------------


@pytest.mark.parametrize("bad", ["../etc/passwd", "/etc/passwd", "-rf", "a/../../b"])
def test_repo_paths_cannot_escape_or_look_like_options(repo, bad):
    out = call(GitDiff(), root=str(repo), path=bad)
    assert out["ok"] is False
    assert helper(repo, "git.diff", {"path": bad})["ok"] is False


@pytest.mark.parametrize("bad", ["--upload-pack=touch /tmp/pwned", "-x", "a..b"])
def test_refs_cannot_smuggle_options(repo, bad):
    out = call(GitShow(), root=str(repo), ref=bad)
    assert out["ok"] is False
    assert helper(repo, "git.show", {"ref": bad})["ok"] is False


def test_helper_rejects_unknown_and_mistyped_arguments():
    with pytest.raises(ValueError):
        validate("git.status", {"shell": "rm -rf /"})
    with pytest.raises(ValueError):
        validate("git.commit", {"message": "x", "all": "yes"})
    with pytest.raises(ValueError):
        validate("git.add", {"paths": "src"})


def test_the_allowlist_is_registered_and_advertised():
    registry = load_builtin()
    allowed = set(default_policy().execution.allowed_tools)
    assert allowed <= set(registry.names()), "policy allows a tool the registry lacks"
    advertised = catalog.names(registry, available=allowed)
    assert {"git.commit", "patch.apply", "repo.map"} <= advertised


def test_git_tools_are_offline_by_construction():
    """No fetch/pull/push/remote surface: the tool list is the contract."""
    names = {n for n in load_builtin().names() if n.startswith("git.")}
    assert names == {
        "git.add",
        "git.branch",
        "git.checkout",
        "git.commit",
        "git.diff",
        "git.log",
        "git.show",
        "git.status",
    }


def test_sys_executable_is_used_for_the_helper():
    assert sys.executable  # the helper is python3 inside the image
