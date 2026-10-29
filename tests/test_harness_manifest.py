"""H-04 manifest integrity and configuration regressions."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from pydantic import ValidationError

from arcen.config import ArcenConfig, load_config, save_config
from arcen.harness import HarnessError
from arcen.harness.manifest import COMPONENT_PATHS, check_model_pin, default_manifest, load_manifest

ROOT = Path(__file__).resolve().parents[1] / "src/arcen"


def copy_components(root):
    for name in (*COMPONENT_PATHS, "harness.toml"):
        dest = root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, dest)
    return root


def test_packaged_manifest_valid_and_frozen():
    m = default_manifest()
    assert m == load_manifest() and set(m.components) == COMPONENT_PATHS
    assert m.model_pin == "provider-configured"
    with pytest.raises(FrozenInstanceError):
        m.schema_version = 2
    with pytest.raises(TypeError):
        m.components["prompts/system.md"] = "x"


@pytest.mark.parametrize("name", sorted(COMPONENT_PATHS))
def test_each_tampered_component_fails_validation(tmp_path, name):
    root = copy_components(tmp_path)
    with (root / name).open("ab") as stream:
        stream.write(b"\n# tampered\n")
    with pytest.raises(HarnessError, match="hash mismatch"):
        load_manifest(root)


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate",
        "unknown",
        "bad_hash",
        "bad_version",
        "bad_pin",
        "extra_component",
        "missing_component",
    ],
)
def test_invalid_manifests_fail_closed(tmp_path, change):
    root = copy_components(tmp_path)
    path = root / "harness.toml"
    text = path.read_text()
    if change == "missing":
        path.unlink()
    elif change == "duplicate":
        path.write_text(
            text.replace("schema_version = 1", "schema_version = 1\nschema_version = 1")
        )
    elif change == "unknown":
        path.write_text(text.replace("schema_version = 1", "schema_version = 1\nunknown = true"))
    elif change == "bad_hash":
        line = next(x for x in text.splitlines() if x.startswith('"prompts/draft.md"'))
        path.write_text(text.replace(line, '"prompts/draft.md" = "0"'))
    elif change == "bad_version":
        path.write_text(text.replace("schema_version = 1", "schema_version = true"))
    elif change == "bad_pin":
        path.write_text(text.replace("provider-configured", "some-model"))
    elif change == "extra_component":
        path.write_text(text + '"../../unsafe" = "' + "a" * 64 + '"\n')
    elif change == "missing_component":
        line = next(x for x in text.splitlines() if x.startswith('"prompts/draft.md"'))
        path.write_text(text.replace(line + "\n", ""))
    with pytest.raises(HarnessError):
        load_manifest(root)


def test_symlink_component_rejected(tmp_path):
    root = copy_components(tmp_path)
    path = root / "prompts/draft.md"
    path.unlink()
    path.symlink_to(ROOT / "prompts/draft.md")
    with pytest.raises(HarnessError, match="symlink"):
        load_manifest(root)


def test_tampered_packaged_prompt_aborts_real_server_boot(tmp_path):
    pkg = tmp_path / "arcen"
    shutil.copytree(ROOT, pkg, ignore=shutil.ignore_patterns("__pycache__"))
    path = pkg / "prompts/forge.md"
    path.write_text(path.read_text() + "tampered\n")
    result = subprocess.run(
        [sys.executable, "-c", "import arcen.server.app"],
        check=False,
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path), "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert "component hash mismatch" in result.stderr


def test_harnessing_config_round_trip_and_cannot_enable_yet(tmp_path):
    cfg = ArcenConfig()
    path = tmp_path / "config.yaml"
    save_config(path, cfg)
    assert load_config(path).harnessing.enabled is False
    with pytest.raises(ValidationError):
        ArcenConfig(harnessing={"enabled": True})


def test_fixed_model_pin_accepts_only_matching_models(tmp_path):
    root = copy_components(tmp_path)
    path = root / "harness.toml"
    path.write_text(path.read_text().replace("provider-configured", "fixed:custom:org/model:tag"))
    manifest = load_manifest(root)
    good = ArcenConfig(provider={"name": "custom", "model": "org/model:tag"})
    check_model_pin(manifest, good)
    bad = good.model_copy(deep=True)
    bad.agents.forge.model = "different"
    with pytest.raises(HarnessError, match="override"):
        check_model_pin(manifest, bad)
    bad = good.model_copy(deep=True)
    bad.provider.model = "other"
    with pytest.raises(HarnessError, match="provider/model"):
        check_model_pin(manifest, bad)


def test_server_enforces_pin_at_boot_and_before_config_update(monkeypatch, tmp_path):
    import arcen.server.app as server

    root = copy_components(tmp_path / "harness")
    path = root / "harness.toml"
    path.write_text(path.read_text().replace("provider-configured", "fixed:custom:one"))
    manifest = load_manifest(root)
    monkeypatch.setattr(server, "default_manifest", lambda: manifest)
    bad = ArcenConfig(provider={"name": "custom", "model": "other"})
    with pytest.raises(HarnessError, match="provider/model"):
        server.ServerState(bad)
    good = ArcenConfig(provider={"name": "custom", "model": "one"})
    state = server.ServerState(good)
    state.config_path = tmp_path / "config.yaml"
    monkeypatch.setattr(server, "STATE", state)
    with pytest.raises(server.HTTPException) as error:
        server.put_config(bad.model_dump())
    assert error.value.status_code == 422
    assert state.config.provider.model == "one"
    assert not state.config_path.exists()
