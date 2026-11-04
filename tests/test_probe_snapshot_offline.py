"""Probe Git reads refuse lazy fetches from local promisor remotes."""

from __future__ import annotations

import io
import os
import subprocess
import tarfile

import pytest
from test_probe_workspace import git, repository

from arcen.harness.probe_workspace import snapshot_git_commit
from arcen.sandbox.workspace import WorkspaceError


@pytest.mark.parametrize("missing", ["commit", "tree", "blob"])
def test_probe_snapshot_refuses_missing_promisor_objects(tmp_path, missing):
    upstream, commit = repository(tmp_path)
    clone = tmp_path / "partial"
    subprocess.run(
        ["git", "clone", "-q", "--no-hardlinks", str(upstream), str(clone)],
        capture_output=True,
        check=True,
    )
    objects = {
        "commit": commit,
        "tree": git(clone, "rev-parse", f"{commit}^{{tree}}"),
        "blob": git(clone, "rev-parse", f"{commit}:src/main.py"),
    }
    git(clone, "config", "remote.origin.promisor", "true")
    git(clone, "config", "remote.origin.partialclonefilter", "blob:none")
    digest = objects[missing]
    loose_object = clone / ".git" / "objects" / digest[:2] / digest[2:]
    assert loose_object.exists()
    loose_object.unlink()
    with pytest.raises(WorkspaceError):
        snapshot_git_commit(clone, commit)
    assert not loose_object.exists()
    assert not list((clone / ".git" / "objects" / "pack").glob("*.pack"))

    # Control: unguarded Git archive really does fetch the absent object from
    # this local promisor. No network is used; this proves the hazard exists.
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
    env.pop("GIT_NO_LAZY_FETCH", None)
    proc = subprocess.run(
        ["git", "-C", str(clone), "archive", "--format=tar", commit],
        env=env,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")
    with tarfile.open(fileobj=io.BytesIO(proc.stdout), mode="r:") as archive:
        assert archive.extractfile("src/main.py").read() == b"print('committed')\n"
    assert list((clone / ".git" / "objects" / "pack").glob("*.pack"))


def test_old_git_without_no_lazy_fetch_fails_before_archive(tmp_path, monkeypatch):
    from arcen.harness import probe_workspace

    repo, commit = repository(tmp_path)
    original = probe_workspace.subprocess.Popen
    calls = []

    def unsupported(argv, **kwargs):
        calls.append(argv)
        # Simulate Git exiting nonzero on the unrecognized global flag.
        return original(["/bin/false"], **kwargs)

    monkeypatch.setattr(probe_workspace.subprocess, "Popen", unsupported)
    with pytest.raises(WorkspaceError):
        snapshot_git_commit(repo, commit)
    assert len(calls) == 1
    assert calls[0][:4] == ["/usr/bin/git", "--no-lazy-fetch", "-C", str(repo)]


def test_reviewed_probe_does_not_admit_or_contact_provider_if_blob_missing(tmp_path, monkeypatch):
    import litellm
    from test_probe_model import configured

    from arcen.harness import probe_container
    from arcen.harness.budget import SharedBudget
    from arcen.harness.probe_execution import run_reviewed_probe

    store, baseline, candidate, config = configured(tmp_path)
    upstream, commit = repository(tmp_path)
    clone = tmp_path / "partial"
    subprocess.run(
        ["git", "clone", "-q", "--no-hardlinks", str(upstream), str(clone)],
        capture_output=True,
        check=True,
    )
    digest = git(clone, "rev-parse", f"{commit}:src/main.py")
    git(clone, "config", "remote.origin.promisor", "true")
    git(clone, "config", "remote.origin.partialclonefilter", "blob:none")
    (clone / ".git" / "objects" / digest[:2] / digest[2:]).unlink()
    monkeypatch.setattr(litellm, "completion", lambda **kw: pytest.fail("provider called"))
    monkeypatch.setattr(
        probe_container, "DockerTurnRegistry", lambda *a, **kw: pytest.fail("Docker called")
    )
    budget = SharedBudget(max_trials=1, max_model_calls=4, max_judge_calls=1, admission_seconds=60)
    with pytest.raises(WorkspaceError):
        run_reviewed_probe(
            store,
            baseline,
            candidate,
            "inspect project",
            config,
            repo=clone,
            commit=commit,
            reviewed_inputs=True,
            budget=budget,
        )
    snap = budget.snapshot()
    assert (snap.trials, snap.model_calls, snap.judge_calls) == (0, 0, 0)
    assert not snap.stopped


def test_sha256_local_git_repository_when_supported(tmp_path):
    repo = tmp_path / "sha256-repo"
    proc = subprocess.run(
        ["git", "init", "-q", "--object-format=sha256", str(repo)],
        capture_output=True,
        check=False,
    )
    if proc.returncode:
        pytest.skip("Git does not support SHA-256 repositories")
    (repo / "work.txt").write_text("reviewed\n")
    git(repo, "add", "work.txt")
    git(repo, "commit", "-qm", "fixture")
    commit = git(repo, "rev-parse", "HEAD")
    assert len(commit) == 64
    snapshot = snapshot_git_commit(repo, commit)
    assert snapshot.commit == commit
    with tarfile.open(fileobj=io.BytesIO(snapshot.archive), mode="r:") as archive:
        assert archive.extractfile("work.txt").read() == b"reviewed\n"
