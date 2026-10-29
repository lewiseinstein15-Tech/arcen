"""H-03 policy safety, boot and actual mock-boundary enforcement regressions."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_turn_isolation import FakeDocker

from arcen.config import ArcenConfig
from arcen.guardrails import PolicyError, load_policy
from arcen.sandbox import turn

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "src/arcen/guardrails/policy.yaml"


def policy_file(tmp_path, text=None):
    p = tmp_path / "policy.yaml"
    p.write_text(POLICY.read_text() if text is None else text, encoding="utf-8")
    return p


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("schema_version: 1", "schema_version: true"),
        ("schema_version: 1", "schema_version: 2"),
        ("backend: docker", "backend: process"),
        ("network: none", "network: bridge"),
        ("host_mounts: false", "host_mounts: true"),
        ("host_mounts: false", "host_mounts: 0"),
        ("host_process_environment: false", "host_process_environment: true"),
        ("read_only_rootfs: true", "read_only_rootfs: false"),
        ("no_new_privileges: true", "no_new_privileges: false"),
        ("drop_all_capabilities: true", "drop_all_capabilities: false"),
        ("process_fallback: false", "process_fallback: true"),
        ('user: "65534:65534"', 'user: "0:0"'),
        ("- bash", "- file.write"),
        ("- bash", "- bash\n    - bash"),
        ("max_pids: 128", "max_pids: 129"),
        ("max_pids: 128", 'max_pids: "64"'),
        ("max_output_bytes: 262144", "max_output_bytes: 262145"),
        ("max_output_bytes: 262144", "max_output_bytes: 1500"),
        ("mode: input_snapshot", "mode: host_mount"),
        ("follow_symlinks: false", "follow_symlinks: true"),
        ("copy_back: false", "copy_back: true"),
        ("max_entries: 10000", "max_entries: 10001"),
        ("max_file_bytes: 67108864", "max_file_bytes: 67108865"),
        ("schema_version: 1", "schema_version: 1\nsurprise: true"),
        ("backend: docker", "backend: docker\n  backend: docker"),
        ("schema_version: 1", "schema_version: 1\nschema_version: 1"),
        ("execution:", "execution: &base"),
        ("execution:", "execution: !custom"),
        ("execution:", "execution: ["),
    ],
)
def test_rejects_invalid_or_unsafe_policy(tmp_path, old, new):
    text = POLICY.read_text()
    assert old in text
    with pytest.raises(PolicyError):
        load_policy(policy_file(tmp_path, text.replace(old, new, 1)))


def test_missing_bad_encoding_empty_large_and_symlink_rejected(tmp_path):
    p = tmp_path / "policy.yaml"
    with pytest.raises(PolicyError):
        load_policy(p)
    p.write_bytes(b"\xff")
    with pytest.raises(PolicyError):
        load_policy(p)
    p.write_bytes(b"")
    with pytest.raises(PolicyError):
        load_policy(p)
    p.write_bytes(b"#" * (64 * 1024 + 1))
    with pytest.raises(PolicyError):
        load_policy(p)
    p.write_text(POLICY.read_text())
    link = tmp_path / "link.yaml"
    link.symlink_to(p)
    with pytest.raises(PolicyError, match="symlink"):
        load_policy(link)
    directory = tmp_path / "guardrails-link"
    directory.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(PolicyError, match="symlink"):
        load_policy(directory / "policy.yaml")


def test_policy_and_nested_values_are_immutable_and_snapshot_is_detached(tmp_path):
    policy = load_policy(policy_file(tmp_path))
    with pytest.raises(ValidationError):
        policy.execution.max_pids = 200
    with pytest.raises(ValidationError):
        policy.workspace.max_entries = 99999
    with pytest.raises(TypeError):
        policy.execution.allowed_tools[0] = "file.write"
    copy = policy.snapshot()
    copy["execution"]["allowed_tools"].append("file.write")
    assert policy.execution.allowed_tools == ("bash",)
    assert policy.snapshot()["execution"]["max_pids"] == 128


@pytest.mark.parametrize("mode", ["missing", "unsafe", "duplicate"])
def test_invalid_packaged_policy_aborts_real_server_boot(tmp_path, mode):
    pkg = tmp_path / "arcen"
    shutil.copytree(ROOT / "src/arcen", pkg, ignore=shutil.ignore_patterns("__pycache__"))
    policy = pkg / "guardrails/policy.yaml"
    if mode == "missing":
        policy.unlink()
    elif mode == "unsafe":
        policy.write_text(
            policy.read_text().replace("process_fallback: false", "process_fallback: true")
        )
    else:
        policy.write_text(
            policy.read_text().replace("backend: docker", "backend: docker\n  backend: docker")
        )
    env = {**os.environ, "PYTHONPATH": str(tmp_path), "HOME": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, "-c", "import arcen.server.app"],
        check=False,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert "PolicyError" in result.stderr


def test_tightened_policy_reaches_status_and_enforces_resources(monkeypatch, tmp_path):
    text = POLICY.read_text().replace("max_pids: 128", "max_pids: 8")
    text = text.replace("max_output_bytes: 262144", "max_output_bytes: 1024")
    text = text.replace("max_entries: 10000", "max_entries: 1")
    text = text.replace("max_file_bytes: 67108864", "max_file_bytes: 3")
    policy = load_policy(policy_file(tmp_path, text))
    monkeypatch.setattr(turn, "default_policy", lambda: policy)
    docker = FakeDocker()
    docker.container.attrs["HostConfig"]["PidsLimit"] = 8
    reg = turn.DockerTurnRegistry(ArcenConfig(), docker_client=docker)
    assert docker.run_args["pids_limit"] == 8
    docker.output = [(b"x" * 1025, b"")]
    assert "exceeded 1 KiB" in reg.dispatch("bash", {"cmd": "yes"})["error"]
    assert docker.container.killed
    status = turn.execution_status(ArcenConfig())
    assert status["policy"] == policy.snapshot()
    status["policy"]["execution"]["max_pids"] = 500
    assert policy.execution.max_pids == 8
    workspace = tmp_path / "work"
    workspace.mkdir()
    (workspace / "x").write_text("four")
    with pytest.raises(turn.IsolationUnavailable, match="3 file bytes"):
        turn.DockerTurnRegistry(ArcenConfig(), docker_client=FakeDocker(), workspace=workspace)
    (workspace / "x").write_text("ok")
    (workspace / "y").write_text("ok")
    with pytest.raises(turn.IsolationUnavailable, match="1 entries"):
        turn.DockerTurnRegistry(ArcenConfig(), docker_client=FakeDocker(), workspace=workspace)


def test_tightened_allowlist_and_pid_inspection_fail_closed(monkeypatch, tmp_path):
    text = POLICY.read_text().replace("allowed_tools:\n    - bash", "allowed_tools: []")
    text = text.replace("max_pids: 128", "max_pids: 8")
    policy = load_policy(policy_file(tmp_path, text))
    monkeypatch.setattr(turn, "default_policy", lambda: policy)
    docker = FakeDocker()
    with pytest.raises(turn.IsolationUnavailable):
        turn.DockerTurnRegistry(ArcenConfig(), docker_client=docker)
    assert docker.container.removed
    docker = FakeDocker()
    docker.container.attrs["HostConfig"]["PidsLimit"] = 8
    reg = turn.DockerTurnRegistry(ArcenConfig(), docker_client=docker)
    assert not reg.dispatch("bash", {"cmd": "true"})["ok"]
    assert not docker.container.calls
    assert turn.execution_status(ArcenConfig())["supported_tools"] == []
