"""Probe preflight safety; no candidate is ever executed by this module."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import MappingProxyType

import pytest

from arcen.config import ArcenConfig
from arcen.harness import HarnessError
from arcen.harness.manifest import Manifest, default_manifest
from arcen.harness.probe import ProbeUnavailable, prepare_probe, run_probe
from arcen.harness.store import HarnessStore

ROOT = Path(__file__).resolve().parents[1] / "src/arcen"
PIN = "fixed:custom:mock-model"


def setup_store(tmp_path):
    store = HarnessStore(tmp_path / "store")
    manifest = default_manifest()
    for path in manifest.components:
        store.put_blob((ROOT / path).read_bytes())
    base = Manifest(1, PIN, manifest.components)
    baseline = store.put_manifest(base)
    config = ArcenConfig(provider={"name": "custom", "model": "mock-model"})
    return store, base, baseline, config


def changed(store, base, path, content, pin=None):
    values = dict(base.components)
    values[path] = store.put_blob(content)
    return store.put_manifest(Manifest(1, pin or base.model_pin, MappingProxyType(values)))


def test_valid_candidate_produces_immutable_plan_but_cannot_run(tmp_path, monkeypatch):
    import socket
    import subprocess

    store, base, baseline, config = setup_store(tmp_path)
    source = store.get_blob(base.components["prompts/forge.md"])
    candidate = changed(store, base, "prompts/forge.md", source + b"additional guidance\n")
    before = {p.name for p in store.objects.iterdir()}
    monkeypatch.setattr(socket.socket, "connect", lambda *a: pytest.fail("unexpected network"))
    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **kw: pytest.fail("unexpected host process")
    )
    plan = prepare_probe(store, baseline, candidate, "private task", config)
    assert plan.changed_paths == ("prompts/forge.md",)
    assert "additional guidance" in plan.prompts.executor_job
    assert "private task" not in repr(plan)
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.task = "other"
    with pytest.raises(ProbeUnavailable, match="not available"):
        run_probe(plan)
    assert {p.name for p in store.objects.iterdir()} == before


def test_baseline_reference_can_be_prepared_with_fixed_pin(tmp_path):
    store, _, baseline, config = setup_store(tmp_path)
    plan = prepare_probe(store, baseline, baseline, "work", config)
    assert plan.changed_paths == () and plan.baseline_id == plan.candidate_id


@pytest.mark.parametrize("path", ["guardrails/policy.yaml", "tools/registry.toml"])
def test_candidate_and_baseline_cannot_replace_protected_components(tmp_path, path):
    store, base, baseline, config = setup_store(tmp_path)
    rogue = changed(store, base, path, b"rogue\n")
    with pytest.raises(HarnessError, match="protected component"):
        prepare_probe(store, baseline, rogue, "work", config)
    with pytest.raises(HarnessError, match="protected component"):
        prepare_probe(store, rogue, rogue, "work", config)


def test_probe_rejects_unpinned_or_mismatched_models(tmp_path):
    store, base, baseline, config = setup_store(tmp_path)
    unpinned = store.put_manifest(Manifest(1, "provider-configured", base.components))
    with pytest.raises(HarnessError, match="fixed model pin"):
        prepare_probe(store, unpinned, unpinned, "work", config)
    changed_model = store.put_manifest(Manifest(1, "fixed:custom:other", base.components))
    with pytest.raises(HarnessError, match="cannot change"):
        prepare_probe(store, baseline, changed_model, "work", config)
    config.agents.forge.model = "other"
    with pytest.raises(HarnessError, match="override"):
        prepare_probe(store, baseline, baseline, "work", config)


def test_corruption_invalid_prompt_and_invalid_task_fail_closed(tmp_path):
    store, base, baseline, config = setup_store(tmp_path)
    broken = changed(store, base, "prompts/forge.md", b"not a prompt\n")
    with pytest.raises(HarnessError):
        prepare_probe(store, baseline, broken, "work", config)
    with pytest.raises(HarnessError, match="task"):
        prepare_probe(store, baseline, baseline, "", config)
    component = base.components["tool-guidance.md"]
    (store.objects / component).write_bytes(b"tampered")
    with pytest.raises(HarnessError, match="integrity"):
        prepare_probe(store, baseline, baseline, "work", config)
