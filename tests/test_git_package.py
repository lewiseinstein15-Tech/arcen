"""Signed package blobs from local Git commits; no checkout or adoption."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import test_harness_package_import as package_import_tests
from test_harness_package_import import object_names, tty
from test_probe_workspace import git, repository

import arcen
from arcen.harness.cli import main
from arcen.harness.git_package import read_git_package
from arcen.harness.package import MAX_PACKAGE_BYTES, verify_package
from arcen.harness.resolver import HarnessError
from arcen.harness.selection import resolve_packaged_baseline


@pytest.fixture
def scenario(tmp_path):
    return package_import_tests.scenario.__wrapped__(tmp_path)


def setup_repo(tmp_path, data):
    repo, _ = repository(tmp_path)
    (repo / "packages").mkdir()
    (repo / "packages" / "candidate.json").write_bytes(data)
    git(repo, "add", "packages/candidate.json")
    git(repo, "commit", "-qm", "signed test package")
    return repo, git(repo, "rev-parse", "HEAD")


def command(action, store, candidate, public, repo, commit, path="packages/candidate.json"):
    return [
        "--store",
        str(store),
        "package",
        action,
        "--manifest",
        candidate,
        "--public-key",
        public.hex(),
        "--repo",
        str(repo),
        "--commit",
        commit,
        "--path",
        path,
    ]


def test_reads_exact_committed_bytes_not_worktree_or_ref(scenario, tmp_path):
    _, _, candidate, public, package, _, _ = scenario
    repo, commit = setup_repo(tmp_path, package)
    (repo / "packages/candidate.json").write_text("untrusted worktree change")
    git(repo, "add", "packages/candidate.json")
    git(repo, "commit", "-qm", "different worktree version")
    assert read_git_package(repo, commit, "packages/candidate.json") == package
    assert verify_package(
        read_git_package(repo, commit, "packages/candidate.json"), candidate, public
    )
    with pytest.raises(HarnessError):
        read_git_package(repo, "HEAD", "packages/candidate.json")
    assert (repo / "packages/candidate.json").read_text() == "untrusted worktree change"


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/tmp/a",
        "../a",
        "a/../b",
        "a//b",
        "./a",
        ".git/config",
        ":(glob)*",
        "a/*.json",
        "a\\b",
        "a\nfile",
        "é.json",
        "x" * 129,
        "a/" * 300,
    ],
)
def test_refuses_unsafe_path_syntax_before_git(scenario, tmp_path, path, monkeypatch):
    repo, commit = setup_repo(tmp_path, scenario[4])
    monkeypatch.setattr(
        "arcen.harness.git_package._run_git", lambda *_a, **_k: pytest.fail("Git called")
    )
    with pytest.raises(HarnessError, match="path"):
        read_git_package(repo, commit, path)


@pytest.mark.parametrize("commit", ["HEAD", "HEAD~1", "0" * 39, "A" * 40, "0" * 41, "-" * 40, None])
def test_refuses_abbreviated_or_symbolic_commit_before_git(scenario, tmp_path, commit, monkeypatch):
    repo, _ = setup_repo(tmp_path, scenario[4])
    monkeypatch.setattr(
        "arcen.harness.git_package._run_git", lambda *_a, **_k: pytest.fail("Git called")
    )
    with pytest.raises(HarnessError, match="commit"):
        read_git_package(repo, commit, "packages/candidate.json")


def test_refuses_symlinks_gitlinks_directories_missing_and_noncommit(scenario, tmp_path):
    repo, _ = setup_repo(tmp_path, scenario[4])
    (repo / "packages/link").symlink_to("candidate.json")
    git(repo, "add", "packages/link")
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{base},packages/submodule")
    git(repo, "commit", "-qm", "symlink and gitlink")
    commit = git(repo, "rev-parse", "HEAD")
    for path in ("packages/link", "packages/submodule", "packages", "missing"):
        with pytest.raises(HarnessError):
            read_git_package(repo, commit, path)
    blob = git(repo, "rev-parse", f"{commit}:packages/candidate.json")
    with pytest.raises(HarnessError, match="commit"):
        read_git_package(repo, blob, "packages/candidate.json")
    link = tmp_path / "repo-link"
    link.symlink_to(repo, target_is_directory=True)
    with pytest.raises(HarnessError, match="symlink"):
        read_git_package(link, commit, "packages/candidate.json")


def test_oversize_committed_blob_refused(scenario, tmp_path):
    repo, _ = setup_repo(tmp_path, scenario[4])
    (repo / "packages/oversize.json").write_bytes(b"x" * (MAX_PACKAGE_BYTES + 1))
    git(repo, "add", "packages/oversize.json")
    git(repo, "commit", "-qm", "oversize package")
    commit = git(repo, "rev-parse", "HEAD")
    with pytest.raises(HarnessError):
        read_git_package(repo, commit, "packages/oversize.json")


def test_verify_git_is_offline_read_only_and_does_not_run_hooks(scenario, tmp_path, capsys):
    store, _, candidate, public, package, _, _ = scenario
    repo, commit = setup_repo(tmp_path, package)
    hook = repo / ".git/hooks/post-checkout"
    marker = tmp_path / "hook-ran"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)
    before = object_names(store)
    before_db = (store.root / "lineage.sqlite3").read_bytes()
    missing = tmp_path / "not-created"
    assert main(command("verify-git", missing, candidate, public, repo, commit)) == 0
    output = capsys.readouterr().out
    assert f"Committed package: {commit}:packages/candidate.json" in output
    assert "Verified manifest" in output and "not imported, activated or adopted" in output
    assert not missing.exists() and not marker.exists()
    assert (
        object_names(store) == before and (store.root / "lineage.sqlite3").read_bytes() == before_db
    )


def test_import_git_requires_tty_and_confirmation_and_keeps_verified_bytes(
    scenario, tmp_path, monkeypatch, capsys
):
    store, base, candidate, public, package, _, components = scenario
    repo, commit = setup_repo(tmp_path, package)
    before = object_names(store)
    db = (store.root / "lineage.sqlite3").read_bytes()
    argv = command("import-git", store.root, candidate, public, repo, commit)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert main(argv) == 1 and object_names(store) == before
    assert "interactive terminal" in capsys.readouterr().err
    tty(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: "no")
    assert main(argv) == 1 and object_names(store) == before
    assert "cancelled" in capsys.readouterr().err

    def confirm(_):
        (repo / "packages/candidate.json").write_bytes(b"changed after review")
        git(repo, "add", "packages/candidate.json")
        git(repo, "commit", "-qm", "moved head during confirmation")
        return f"IMPORT {candidate}"

    monkeypatch.setattr("builtins.input", confirm)
    assert main(argv) == 0
    assert "Verified objects stored" in capsys.readouterr().out
    assert store.get_manifest(candidate).components == components
    assert (store.root / "lineage.sqlite3").read_bytes() == db
    assert resolve_packaged_baseline("adopted", str(store.root)) == base


def test_invalid_key_fails_before_prompt_and_import(scenario, tmp_path, monkeypatch, capsys):
    store, _, candidate, public, package, _, _ = scenario
    repo, commit = setup_repo(tmp_path, package)
    before = object_names(store)
    tty(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("confirmation reached"))
    wrong = bytes([public[0] ^ 1]) + public[1:]
    assert main(command("import-git", store.root, candidate, wrong, repo, commit)) == 1
    assert object_names(store) == before
    assert "Verified objects stored" not in capsys.readouterr().out


def test_local_sha256_git_repository_when_supported(scenario, tmp_path):
    repo = tmp_path / "sha256-repo"
    proc = subprocess.run(
        ["git", "init", "-q", "--object-format=sha256", str(repo)],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        pytest.skip("installed Git does not support SHA-256 repositories")
    (repo / "package.json").write_bytes(scenario[4])
    git(repo, "add", "package.json")
    git(repo, "commit", "-qm", "test sha256")
    commit = git(repo, "rev-parse", "HEAD")
    assert len(commit) == 64
    assert read_git_package(repo, commit, "package.json") == scenario[4]
    assert verify_package(read_git_package(repo, commit, "package.json"), scenario[2], scenario[3])


def test_invalid_repository_is_safe_error(scenario, tmp_path):
    repo, commit = setup_repo(tmp_path, scenario[4])
    for invalid in (None, 9, str(repo / "missing"), "~missing-user-for-arcen/nope", "bad\0path"):
        with pytest.raises(HarnessError):
            read_git_package(invalid, commit, "packages/candidate.json")


def test_installed_cli_reads_committed_package_outside_checkout(scenario, tmp_path):
    _, _, candidate, public, package, _, _ = scenario
    repo, commit = setup_repo(tmp_path, package)
    env = os.environ.copy()
    env.update(HOME=str(tmp_path), PYTHONPATH=str(Path(arcen.__file__).resolve().parent.parent))
    cmd = [
        sys.executable,
        "-m",
        "arcen.cli",
        "harness",
        "package",
        "verify-git",
        "--manifest",
        candidate,
        "--public-key",
        public.hex(),
        "--repo",
        str(repo),
        "--commit",
        commit,
        "--path",
        "packages/candidate.json",
    ]
    result = subprocess.run(
        cmd, env=env, cwd=tmp_path, capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 0, result.stderr
    assert f"Committed package: {commit}:packages/candidate.json" in result.stdout
    assert "not imported, activated or adopted" in result.stdout
    assert not (tmp_path / ".arcen").exists()


def test_promisor_missing_blob_fails_without_lazy_fetch(scenario, tmp_path):
    upstream, commit = setup_repo(tmp_path, scenario[4])
    clone = tmp_path / "partial"
    subprocess.run(
        ["git", "clone", "-q", "--no-hardlinks", str(upstream), str(clone)],
        capture_output=True,
        check=True,
    )
    blob = git(clone, "rev-parse", f"{commit}:packages/candidate.json")
    git(clone, "config", "remote.origin.promisor", "true")
    git(clone, "config", "remote.origin.partialclonefilter", "blob:none")
    loose_blob = clone / ".git" / "objects" / blob[:2] / blob[2:]
    assert loose_blob.exists()
    loose_blob.unlink()
    with pytest.raises(HarnessError, match="cannot read committed package"):
        read_git_package(clone, commit, "packages/candidate.json")
    assert not loose_blob.exists()
    # Control: normal Git lazy-fetches that missing object from the local
    # promisor. This establishes that the test actually exercises the hazard.
    assert git(clone, "cat-file", "blob", blob).encode() == scenario[4]
