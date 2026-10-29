"""Real local Git snapshots and adversarial archive validation (no Docker)."""

from __future__ import annotations

import io
import os
import subprocess
import tarfile
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from arcen.harness import probe_workspace
from arcen.harness.probe_workspace import snapshot_git_commit
from arcen.sandbox.workspace import WorkspaceError


def git(repo: Path, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, env=env, capture_output=True, text=True
    ).stdout.strip()


def repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "src").mkdir()
    (repo / "src/main.py").write_text("print('committed')\n")
    (repo / "README.md").write_text("reference\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "baseline")
    return repo, git(repo, "rev-parse", "HEAD")


def read_archive(snapshot):
    with tarfile.open(fileobj=io.BytesIO(snapshot.archive), mode="r:") as archive:
        return {item.name: archive.extractfile(item).read() for item in archive if item.isfile()}


def test_real_git_snapshot_is_deterministic_and_ignores_worktree_and_untracked(tmp_path):
    repo, commit = repository(tmp_path)
    (repo / "src/main.py").write_text("modified locally\n")
    (repo / ".env").write_text("untracked secret")
    first = snapshot_git_commit(repo, commit)
    second = snapshot_git_commit(repo, commit)
    assert first.sha256 == second.sha256 and first.archive == second.archive
    assert read_archive(first) == {
        "README.md": b"reference\n",
        "src/main.py": b"print('committed')\n",
    }
    assert first.commit == commit and first.file_bytes == len(b"reference\n") + len(
        b"print('committed')\n"
    )
    assert "committed" not in repr(first)
    with pytest.raises(FrozenInstanceError):
        first.commit = "other"


def test_committed_secret_paths_and_symlinks_are_rejected(tmp_path):
    repo, _ = repository(tmp_path)
    (repo / ".env").write_text("tracked secret")
    git(repo, "add", "-f", ".env")
    git(repo, "commit", "-qm", "secret")
    with pytest.raises(WorkspaceError, match="credential filename"):
        snapshot_git_commit(repo, git(repo, "rev-parse", "HEAD"))
    git(repo, "rm", "-q", ".env")
    (repo / "link").symlink_to("/etc/passwd")
    git(repo, "add", "link")
    git(repo, "commit", "-qm", "symlink")
    with pytest.raises(WorkspaceError, match="link or special"):
        snapshot_git_commit(repo, git(repo, "rev-parse", "HEAD"))


def test_requires_full_commit_and_real_repo(tmp_path):
    repo, commit = repository(tmp_path)
    for value in ("HEAD", commit[:8], "-h", "f" * 39, "F" * 40):
        with pytest.raises(WorkspaceError, match="full lowercase"):
            snapshot_git_commit(repo, value)
    tree = git(repo, "rev-parse", "HEAD^{tree}")
    with pytest.raises(WorkspaceError, match="not a commit"):
        snapshot_git_commit(repo, tree)
    link = tmp_path / "link"
    link.symlink_to(repo, target_is_directory=True)
    with pytest.raises(WorkspaceError, match="symlink"):
        snapshot_git_commit(link, commit)
    with pytest.raises(WorkspaceError):
        snapshot_git_commit(tmp_path / "missing", commit)


def build_tar(name, data=b"x", type_=tarfile.REGTYPE):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        entry = tarfile.TarInfo(name)
        entry.type = type_
        entry.size = len(data) if type_ == tarfile.REGTYPE else 0
        archive.addfile(entry, io.BytesIO(data) if type_ == tarfile.REGTYPE else None)
    return output.getvalue()


@pytest.mark.parametrize(
    "name",
    [
        "../outside",
        "/absolute",
        "a/../b",
        "a//b",
        "dir/.ssh/key",
        ".env.local",
        "secrets/key.pem",
        "back\\slash",
    ],
)
def test_unsafe_archive_members_rejected(tmp_path, monkeypatch, name):
    repo, commit = repository(tmp_path)
    raw = build_tar(name)
    monkeypatch.setattr(
        probe_workspace,
        "_run_git",
        lambda repo, args, **kw: b"commit\n" if args[0] == "cat-file" else raw,
    )
    with pytest.raises(WorkspaceError):
        snapshot_git_commit(repo, commit)


def test_bytes_and_entries_use_current_policy_limits(tmp_path, monkeypatch):
    repo, commit = repository(tmp_path)
    base = probe_workspace.default_policy()
    tiny = base.model_copy(
        update={
            "workspace": base.workspace.model_copy(update={"max_entries": 1, "max_file_bytes": 3})
        }
    )
    monkeypatch.setattr(probe_workspace, "default_policy", lambda: tiny)
    with pytest.raises(WorkspaceError, match="limit"):
        snapshot_git_commit(repo, commit)


def test_git_subprocess_environment_has_no_inherited_credentials(tmp_path, monkeypatch):
    repo, commit = repository(tmp_path)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "very-sensitive")
    calls = []
    original = probe_workspace.subprocess.Popen

    def capture(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(probe_workspace.subprocess, "Popen", capture)
    snapshot_git_commit(repo, commit)
    assert len(calls) == 2
    for args, kwargs in calls:
        assert kwargs["env"].get("AWS_SECRET_ACCESS_KEY") is None
        assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
        assert kwargs.get("shell", False) is False
        assert args[0][0] == "/usr/bin/git"


def test_archive_importer_accepts_normalized_git_snapshot(tmp_path):
    from arcen.sandbox.workspace import CONTAINER_IMPORTER

    repo, commit = repository(tmp_path)
    snapshot = snapshot_git_commit(repo, commit)
    target = tmp_path / "sandbox"
    target.mkdir()
    proc = subprocess.run(
        [os.sys.executable, "-c", CONTAINER_IMPORTER, str(len(snapshot.archive))],
        input=snapshot.archive,
        cwd=target,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert (target / "src/main.py").read_text() == "print('committed')\n"
    assert not (target / ".git").exists()


def test_malformed_and_oversized_archive_are_rejected(tmp_path, monkeypatch):
    repo, commit = repository(tmp_path)
    monkeypatch.setattr(
        probe_workspace,
        "_run_git",
        lambda repo, args, **kw: b"commit\n" if args[0] == "cat-file" else b"not tar",
    )
    with pytest.raises(WorkspaceError, match="invalid Git archive"):
        snapshot_git_commit(repo, commit)


def test_materialized_snapshot_is_private_disposable_and_repeatable(tmp_path):
    from arcen.harness.probe_workspace import materialize_git_snapshot

    repo, commit = repository(tmp_path)
    snapshot = snapshot_git_commit(repo, commit)
    with materialize_git_snapshot(snapshot) as first:
        assert first.stat().st_mode & 0o777 == 0o700
        assert (first / "src/main.py").read_text() == "print('committed')\n"
        (first / "src/main.py").write_text("probe only\n")
        assert (repo / "src/main.py").read_text() == "print('committed')\n"
    assert not first.exists()
    with materialize_git_snapshot(snapshot) as second:
        assert second != first
        assert (second / "src/main.py").read_text() == "print('committed')\n"
    assert not second.exists()


def test_materializer_revalidates_forged_snapshot(tmp_path):
    import hashlib
    from dataclasses import replace

    from arcen.harness.probe_workspace import GitSnapshot, materialize_git_snapshot

    repo, commit = repository(tmp_path)
    valid = snapshot_git_commit(repo, commit)
    with (
        pytest.raises(WorkspaceError, match="integrity"),
        materialize_git_snapshot(replace(valid, archive=valid.archive + b"extra")),
    ):
        pytest.fail("must not yield")
    with (
        pytest.raises(WorkspaceError, match="metadata mismatch"),
        materialize_git_snapshot(replace(valid, entries=999)),
    ):
        pytest.fail("must not yield")
    for name, mode in (("../escape", tarfile.REGTYPE), ("link", tarfile.SYMTYPE)):
        evil = build_tar(name, type_=mode)
        forged = GitSnapshot(commit, hashlib.sha256(evil).hexdigest(), 1, 1, evil)
        with pytest.raises(WorkspaceError), materialize_git_snapshot(forged):
            pytest.fail("must not yield")
    assert not (tmp_path / "escape").exists()


def test_materializer_rechecks_tightened_runtime_limits(tmp_path, monkeypatch):
    from arcen.harness.probe_workspace import materialize_git_snapshot

    repo, commit = repository(tmp_path)
    snapshot = snapshot_git_commit(repo, commit)
    base = probe_workspace.default_policy()
    tiny = base.model_copy(
        update={"workspace": base.workspace.model_copy(update={"max_entries": 1})}
    )
    monkeypatch.setattr(probe_workspace, "default_policy", lambda: tiny)
    with pytest.raises(WorkspaceError, match="entry limit"), materialize_git_snapshot(snapshot):
        pytest.fail("must not yield")
