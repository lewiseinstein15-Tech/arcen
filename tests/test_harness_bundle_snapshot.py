"""Packaged consumers use exactly the bytes covered by a single manifest."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import arcen
from arcen.harness.manifest import COMPONENT_PATHS, load_bundle

ROOT = Path(arcen.__file__).resolve().parent


def copy_package(tmp_path):
    package = tmp_path / "arcen"
    shutil.copytree(ROOT, package, ignore=shutil.ignore_patterns("__pycache__"))
    return package


def run_package(tmp_path, code):
    env = {**os.environ, "PYTHONPATH": str(tmp_path), "HOME": str(tmp_path)}
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_bundle_snapshots_verified_bytes_and_cannot_be_mutated(tmp_path):
    package = copy_package(tmp_path)
    bundle = load_bundle(package)
    assert set(bundle.components) == COMPONENT_PATHS
    for name, raw in bundle.components.items():
        assert hashlib.sha256(raw).hexdigest() == bundle.manifest.components[name]
    original = bundle.components["prompts/forge.md"]
    (package / "prompts/forge.md").write_bytes(b"changed later\n")
    assert bundle.components["prompts/forge.md"] == original
    with pytest.raises(TypeError):
        bundle.components["prompts/forge.md"] = b"changed"
    with pytest.raises(FrozenInstanceError):
        bundle.components = {}


def test_default_consumers_use_same_verified_bytes_not_later_disk_edits(tmp_path):
    copy_package(tmp_path)
    code = r"""
from pathlib import Path
from arcen.harness.manifest import default_bundle, default_manifest
bundle = default_bundle()
root = Path('arcen')
# Simulate changes after verification but before the consuming modules load.
for name in bundle.components:
    (root / name).write_text('tampered after snapshot\n')
(root / 'harness.toml').write_text('invalid later manifest\n')
from arcen.harness.resolver import default_prompts, HarnessResolver
from arcen.guardrails import default_policy, load_policy
from arcen.tools.registry import load_builtin
from arcen.llm.client import Client
prompts = default_prompts()
assert prompts == HarnessResolver().resolve() == Client().prompts
assert prompts.executor_job.startswith('you execute exactly one tool step')
assert default_policy() == load_policy()
assert default_policy().execution.backend == 'docker'
registry = load_builtin()
assert len(registry) == 40 and 'bash' in registry
assert default_manifest() is bundle.manifest
print('SINGLE VERIFIED SNAPSHOT OK: prompts, policy, registry, manifest')
"""
    result = run_package(tmp_path, code)
    assert result.returncode == 0, result.stderr
    assert "SINGLE VERIFIED SNAPSHOT OK" in result.stdout


@pytest.mark.parametrize("module", ["arcen.llm.client", "arcen.agents.draft"])
def test_tampered_prompt_refused_before_prompt_consumer_import(tmp_path, module):
    package = copy_package(tmp_path)
    with (package / "prompts/forge.md").open("ab") as f:
        f.write(b"changed\n")
    result = run_package(tmp_path, f"import {module}")
    assert result.returncode != 0
    assert "component hash mismatch: prompts/forge.md" in result.stderr


def test_semantically_unsafe_policy_rejected_even_when_manifest_hash_updated(tmp_path):
    package = copy_package(tmp_path)
    policy = package / "guardrails/policy.yaml"
    original_digest = hashlib.sha256(policy.read_bytes()).hexdigest()
    policy.write_text(
        policy.read_text().replace("process_fallback: false", "process_fallback: true")
    )
    changed_digest = hashlib.sha256(policy.read_bytes()).hexdigest()
    manifest = package / "harness.toml"
    manifest.write_text(manifest.read_text().replace(original_digest, changed_digest))
    result = run_package(tmp_path, "import arcen.server.app")
    assert result.returncode != 0
    assert "PolicyError" in result.stderr


def test_concurrent_first_default_bundle_call_captures_exactly_once(tmp_path):
    copy_package(tmp_path)
    code = r"""
import threading, time
from concurrent.futures import ThreadPoolExecutor
import arcen.harness.manifest as module
original = module.load_bundle
count = 0
start = threading.Barrier(12)
def slow():
    global count
    count += 1
    time.sleep(0.1)
    return original()
module.load_bundle = slow
def get():
    start.wait()
    return module.default_bundle()
with ThreadPoolExecutor(max_workers=12) as pool:
    results = list(pool.map(lambda _: get(), range(12)))
assert count == 1, count
assert all(item is results[0] for item in results)
print('ONE SNAPSHOT FOR 12 CONCURRENT CALLERS')
"""
    result = run_package(tmp_path, code)
    assert result.returncode == 0, result.stderr
    assert "ONE SNAPSHOT FOR 12 CONCURRENT CALLERS" in result.stdout


def test_tampered_package_yields_headless_json_error_not_import_traceback(tmp_path):
    import json

    package = copy_package(tmp_path)
    with (package / "prompts/forge.md").open("ab") as f:
        f.write(b"changed\n")
    env = {**os.environ, "PYTHONPATH": str(tmp_path), "HOME": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, "-m", "arcen.cli", "run", "test", "--json"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 1
    envelope = json.loads(result.stdout)
    assert envelope["status"] == "error" and envelope["error"]["code"] == "HEADLESS_FAILED"
    assert "component hash mismatch" in envelope["error"]["message"]
    assert envelope["events"] == [] and "Traceback" not in result.stderr
