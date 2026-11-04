"""Refuse repository-configured Git filters before host-side archive."""

from __future__ import annotations

import io
import shlex
import subprocess
import tarfile

import pytest
from test_probe_workspace import git, repository

from arcen.harness import probe_workspace
from arcen.harness.probe_workspace import snapshot_git_commit
from arcen.sandbox.workspace import WorkspaceError


def repository_with_attribute(tmp_path):
    repo, _ = repository(tmp_path)
    (repo / ".gitattributes").write_text("src/main.py filter=evil\nREADME.md export-ignore\n")
    git(repo, "add", ".gitattributes")
    git(repo, "commit", "-qm", "attributes")
    return repo, git(repo, "rev-parse", "HEAD")


def test_real_smudge_filter_is_refused_before_execution_with_archive_control(tmp_path):
    repo, commit = repository_with_attribute(tmp_path)
    marker = tmp_path / "filter-was-executed"
    git(
        repo,
        "config",
        "filter.evil.smudge",
        f"sh -c 'echo fired > {shlex.quote(str(marker))}; cat'",
    )
    with pytest.raises(WorkspaceError, match="filter configuration") as exc:
        snapshot_git_commit(repo, commit)
    assert str(marker) not in str(exc.value)
    assert not marker.exists()
    # Control verifies unguarded Git really executes the configured host filter.
    archive = subprocess.run(
        ["git", "--no-lazy-fetch", "-C", str(repo), "archive", "--format=tar", commit],
        capture_output=True,
        check=True,
        timeout=20,
    )
    assert marker.read_text() == "fired\n"
    with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as tar:
        assert tar.extractfile("src/main.py").read() == b"print('committed')\n"
        assert "README.md" not in tar.getnames()


@pytest.mark.parametrize(
    "key,value",
    [
        ("filter.evil.process", "this command must not run"),
        ("filter.evil.smudge", ""),
        ("filter.Unused.required", "true"),
        ("filter.unused.clean", "cat"),
    ],
)
def test_any_configured_filter_is_rejected_even_when_unused(tmp_path, key, value):
    repo, commit = repository(tmp_path)
    git(repo, "config", key, value)
    with pytest.raises(WorkspaceError, match="filter configuration"):
        snapshot_git_commit(repo, commit)


def test_filter_from_included_config_is_rejected(tmp_path):
    repo, commit = repository_with_attribute(tmp_path)
    included = tmp_path / "included-config"
    included.write_text('[filter "evil"]\n smudge = sh -c false\n')
    git(repo, "config", "include.path", str(included))
    with pytest.raises(WorkspaceError, match="filter configuration"):
        snapshot_git_commit(repo, commit)


def test_unconfigured_filter_attribute_keeps_export_ignore_semantics(tmp_path):
    repo, commit = repository_with_attribute(tmp_path)
    snap = snapshot_git_commit(repo, commit)
    with tarfile.open(fileobj=io.BytesIO(snap.archive), mode="r:") as tar:
        assert "README.md" not in tar.getnames()
        assert tar.extractfile("src/main.py").read() == b"print('committed')\n"


def test_implicit_bool_config_and_unrelated_value_allowed(tmp_path):
    repo, commit = repository(tmp_path)
    with (repo / ".git/config").open("a") as stream:
        stream.write("\n[unrelated]\n enabled\n token = filter.evil.smudge\n")
    assert snapshot_git_commit(repo, commit).commit == commit


def test_oversized_or_malformed_git_config_fails_closed(tmp_path, monkeypatch):
    repo, commit = repository(tmp_path)
    original = probe_workspace._run_git
    for value in (b"core.bare\nfalse", b"\nvalue\0"):

        def fake(path, args, *, max_bytes, result=value):
            return result if args[0] == "config" else original(path, args, max_bytes=max_bytes)

        monkeypatch.setattr(probe_workspace, "_run_git", fake)
        with pytest.raises(WorkspaceError, match="invalid Git configuration"):
            snapshot_git_commit(repo, commit)
    monkeypatch.setattr(probe_workspace, "_run_git", original)
    with (repo / ".git/config").open("a") as stream:
        stream.write(
            "\n[unrelated]\n value = " + "x" * probe_workspace._MAX_GIT_CONFIG_BYTES + "\n"
        )
    with pytest.raises(WorkspaceError):
        snapshot_git_commit(repo, commit)


def test_reviewed_probe_filter_refusal_before_budget_docker_and_provider(tmp_path, monkeypatch):
    import litellm
    from test_probe_model import configured

    from arcen.harness import probe_container
    from arcen.harness.budget import SharedBudget
    from arcen.harness.probe_execution import run_reviewed_probe

    store, baseline, candidate, config = configured(tmp_path)
    repo, commit = repository_with_attribute(tmp_path)
    git(repo, "config", "filter.evil.smudge", "should-never-run")
    monkeypatch.setattr(litellm, "completion", lambda **kw: pytest.fail("provider called"))
    monkeypatch.setattr(
        probe_container, "DockerTurnRegistry", lambda *a, **kw: pytest.fail("Docker called")
    )
    budget = SharedBudget(max_trials=1, max_model_calls=4, max_judge_calls=1, admission_seconds=60)
    with pytest.raises(WorkspaceError, match="filter configuration"):
        run_reviewed_probe(
            store,
            baseline,
            candidate,
            "inspect project",
            config,
            repo=repo,
            commit=commit,
            reviewed_inputs=True,
            budget=budget,
        )
    snap = budget.snapshot()
    assert (snap.trials, snap.model_calls, snap.judge_calls) == (0, 0, 0)
    assert not snap.stopped
