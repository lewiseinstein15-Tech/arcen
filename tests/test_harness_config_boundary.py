"""Disabled harness configuration is explicit and rejected without side effects."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import arcen
from arcen.config import ArcenConfig, HarnessingConfig, load_config
from arcen.harness.manifest import default_manifest


@pytest.mark.parametrize("value", [True, 0, 0.0, 1, "false", "off", None, [], {}])
def test_enabled_requires_boolean_false(value):
    with pytest.raises(ValidationError):
        HarnessingConfig(enabled=value)
    assert HarnessingConfig().enabled is False
    assert HarnessingConfig(enabled=False).enabled is False


@pytest.mark.parametrize("extra", [{"autonomy": True}, {"budget": 10}, {"enabeld": False}])
def test_unimplemented_options_rejected_not_silently_ignored(extra):
    with pytest.raises(ValidationError):
        ArcenConfig.model_validate({"harnessing": {"enabled": False, **extra}})


def test_normal_nested_assignment_is_validated_and_preserves_false():
    cfg = ArcenConfig()
    with pytest.raises(ValidationError):
        cfg.harnessing.enabled = True
    assert cfg.harnessing.enabled is False
    with pytest.raises(ValidationError):
        cfg.harnessing.enabled = 0
    assert cfg.harnessing.enabled is False
    with pytest.raises(ValidationError):
        cfg.harnessing.autonomy = True
    cfg.harnessing.enabled = False


@pytest.mark.parametrize(
    "raw",
    [
        "harnessing: {enabled: true}\n",
        "harnessing: {enabled: 0}\n",
        "harnessing: {enabled: false, autonomy: super-secret-value}\n",
        "harnessing: super-secret-value\n",
    ],
)
def test_yaml_rejects_without_leaking_or_seeding_file(raw, tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(raw)
    monkeypatch.setenv("ARCEN_MODEL_API_KEY", "also-secret")
    with pytest.raises(ValueError, match="invalid harnessing configuration") as exc:
        load_config(path)
    assert "super-secret-value" not in str(exc.value)
    assert "also-secret" not in str(exc.value)
    assert path.read_text() == raw


def test_empty_and_false_sections_round_trip(tmp_path, monkeypatch):
    monkeypatch.delenv("ARCEN_MODEL_API_KEY", raising=False)
    path = tmp_path / "config.yaml"
    for text in ("{}\n", "harnessing: {}\n", "harnessing: {enabled: false}\n"):
        path.write_text(text)
        config = load_config(path)
        assert config.harnessing.enabled is False
        assert ArcenConfig.model_validate(config.model_dump()).harnessing.enabled is False


def test_config_api_rejects_invalid_updates_without_changing_disk_state_or_leaking(
    tmp_path, monkeypatch
):
    import arcen.server.app as server

    path = tmp_path / "config.yaml"
    path.write_text("original file\n")
    marker = object()
    state = SimpleNamespace(
        config=ArcenConfig(), config_path=path, manifest=default_manifest(), llm=marker
    )
    monkeypatch.setattr(server, "STATE", state)
    before = state.config.model_dump()
    with TestClient(server.app) as client:
        for harnessing in (
            {"enabled": True},
            {"enabled": 0},
            {"enabled": False, "autonomy": "super-secret-value"},
        ):
            response = client.put("/api/config", json={"harnessing": harnessing})
            assert response.status_code == 422
            assert response.json() == {"detail": "invalid configuration"}
            assert "super-secret-value" not in response.text
            assert state.config.model_dump() == before
            assert state.llm is marker
            assert path.read_text() == "original file\n"
        response = client.put("/api/config", json={"harnessing": {"enabled": False}})
        assert response.status_code == 200
        assert response.json()["harnessing"] == {"enabled": False}
        assert load_config(path).harnessing.enabled is False


def test_headless_invalid_config_refuses_before_run_without_input_leak(tmp_path):
    path = tmp_path / "config.yaml"
    raw = "harnessing: {enabled: false, autonomy: super-secret-value}\n"
    path.write_text(raw)
    env = os.environ.copy()
    env.update(
        HOME=str(tmp_path),
        ARCEN_CONFIG_PATH=str(path),
        PYTHONPATH=str(Path(arcen.__file__).resolve().parent.parent),
    )
    result = subprocess.run(
        [sys.executable, "-m", "arcen.cli", "run", "do not run", "--json"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 1
    envelope = json.loads(result.stdout)
    assert envelope["status"] == "error"
    assert envelope["error"]["code"] == "HEADLESS_FAILED"
    assert "invalid harnessing configuration" in envelope["error"]["message"]
    assert not envelope["events"]
    assert "super-secret-value" not in result.stdout + result.stderr
    assert path.read_text() == raw
