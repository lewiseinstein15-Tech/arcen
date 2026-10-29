"""Packaged adopted-baseline selection; candidate refs remain blocked."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import replace
from types import MappingProxyType, SimpleNamespace

import pytest
from fake_turn_registry import FakeTurnRegistry
from test_headless import make_state

from arcen.harness.cli import _init
from arcen.harness.manifest import Manifest
from arcen.harness.resolver import HarnessError, default_prompts
from arcen.harness.selection import resolve_packaged_baseline
from arcen.harness.store import HarnessStore
from arcen.headless import execute
from arcen.llm.client import Client


def test_selected_baseline_reaches_actual_turn_with_identical_provider_payloads(
    tmp_path, monkeypatch
):
    from arcen.server import app

    root = str(tmp_path / "harness")
    expected = _init(root)
    calls = []

    def completion(**kwargs):
        calls.append(kwargs["messages"])
        answer = (
            "CODE"
            if len(calls) % 2 == 1
            else '[{"title":"test","tool":"bash","args":{"cmd":"true"}}]'
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=answer))], usage=None
        )

    monkeypatch.setattr(app, "create_turn_registry", lambda config: FakeTurnRegistry())
    state1 = make_state(
        tmp_path / "ordinary", Client(models={"planner": "mock"}, completion_fn=completion)
    )
    state2 = make_state(
        tmp_path / "selected", Client(models={"planner": "mock"}, completion_fn=completion)
    )
    ordinary = execute("run the task", state=state1)
    selected = execute("run the task", state=state2, harness="adopted", harness_store=root)
    assert ordinary["status"] == selected["status"] == "ok"
    assert calls[:2] == calls[2:]
    assert "harness_ref" not in ordinary["events"][0]
    assert selected["events"][0]["harness_ref"] == "sha256:" + expected
    assert resolve_packaged_baseline("refs/heads/adopted", root) == expected


def test_candidate_and_invalid_refs_never_fallback(tmp_path):
    root = str(tmp_path / "harness")
    _init(root)
    for ref in ("candidate", "refs/candidates/example", "refs/heads/other", "", "../adopted"):
        with pytest.raises(HarnessError, match="no harness reference was applied"):
            resolve_packaged_baseline(ref, root)
    with pytest.raises(HarnessError, match="store is missing"):
        resolve_packaged_baseline("adopted", str(tmp_path / "missing"))


def test_corrupt_objects_and_changed_adopted_ref_refuse_selection(tmp_path):
    root = str(tmp_path / "harness")
    baseline_id = _init(root)
    store = HarnessStore(root)
    baseline = store.get_manifest(baseline_id)
    components = dict(baseline.components)
    components["prompts/forge.md"] = store.put_blob(b"## job\nchanged\n")
    altered = store.put_manifest(Manifest(1, baseline.model_pin, MappingProxyType(components)))
    with sqlite3.connect(store.root / "lineage.sqlite3") as db:
        db.execute("UPDATE refs SET node=? WHERE name='refs/heads/adopted'", (altered,))
    with pytest.raises(HarnessError, match="not the packaged baseline"):
        resolve_packaged_baseline("adopted", root)
    with sqlite3.connect(store.root / "lineage.sqlite3") as db:
        db.execute("UPDATE refs SET node=? WHERE name='refs/heads/adopted'", (baseline_id,))
    (store.objects / baseline.components["prompts/forge.md"]).write_bytes(b"corrupt")
    with pytest.raises(HarnessError, match="integrity"):
        resolve_packaged_baseline("adopted", root)


def test_different_or_injected_client_cannot_claim_packaged_identity(tmp_path):
    root = str(tmp_path / "harness")
    _init(root)
    state = make_state(
        tmp_path / "state",
        Client(
            models={"planner": "mock"},
            prompts=replace(default_prompts(), planner_job="not baseline"),
        ),
    )
    with pytest.raises(ValueError, match="does not use"):
        execute("hello", state=state, harness="adopted", harness_store=root)
    state.llm = object()
    with pytest.raises(ValueError, match="does not use"):
        execute("hello", state=state, harness="adopted", harness_store=root)


def test_cli_adopted_baseline_runs_and_missing_store_is_not_ignored(tmp_path):
    root = str(tmp_path / "harness")
    digest = _init(root)
    env = {key: value for key, value in os.environ.items() if not key.startswith("ARCEN_MODEL_")}
    env.update(HOME=str(tmp_path), ARCEN_CONFIG_PATH=str(tmp_path / "none.yaml"))
    command = [
        sys.executable,
        "-m",
        "arcen.headless",
        "hello",
        "--json",
        "--harness",
        "adopted",
        "--harness-store",
    ]
    proc = subprocess.run(
        [*command, root], capture_output=True, text=True, timeout=60, env=env, check=False
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["status"] == "ok"
    assert result["events"][0]["harness_ref"] == "sha256:" + digest
    proc = subprocess.run(
        [*command, str(tmp_path / "missing")],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        check=False,
    )
    assert proc.returncode != 0
    result = json.loads(proc.stdout)
    assert result["status"] == "error" and result["events"] == []
