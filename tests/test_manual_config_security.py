"""Stricter operator-reviewed config parsing for manual harness commands."""

from __future__ import annotations

import os

import pytest
from test_manual_cli import setup, tty
from test_manual_editor_cli import editor_args, scripted
from test_probe_model import SECRET

from arcen.harness.cli import main
from arcen.harness.durable_budget import DurableBudget
from arcen.harness.manual_cli import _config
from arcen.harness.resolver import HarnessError


@pytest.mark.parametrize(
    "text",
    [
        "provider:\n  name: custom\n  name: openai\n  api_key: super-secret\n",
        "provider: {name: custom, api_key: abcdef}\nprovider: {name: openai}\n",
        "provider: &p {name: custom}\nother: *p\n",
        "provider:\n  <<: {name: custom}\n",
        "provider: !!map {name: custom}\n",
        "provider: {123: custom}\n",
        "- not a mapping\n",
        "provider: [unclosed\n",
    ],
)
def test_ambiguous_or_invalid_yaml_fails_without_showing_content(tmp_path, text):
    path = tmp_path / "config.yaml"
    path.write_text(text)
    with pytest.raises(HarnessError, match="invalid campaign configuration") as info:
        _config(str(path))
    assert "super-secret" not in str(info.value)


def test_valid_config_and_env_references_are_frozen_without_env_seeding(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(
        "provider:\n  name: custom\n  model: mock-model\n  base_url: https://provider.example/v1\n  api_key: $MANUAL_TEST_KEY\n"
    )
    monkeypatch.setenv("MANUAL_TEST_KEY", SECRET)
    monkeypatch.setenv("ARCEN_MODEL_API_KEY", "do-not-seed")
    before = path.read_bytes()
    config = _config(str(path))
    monkeypatch.setenv("MANUAL_TEST_KEY", "changed-later")
    assert config.provider.api_key == SECRET
    assert path.read_bytes() == before and os.environ["ARCEN_MODEL_API_KEY"] == "do-not-seed"


def test_bad_config_is_rejected_before_editor_confirmation_or_provider(
    tmp_path, monkeypatch, capsys
):
    store, _, baseline, _, task, config, _, _, budget, _ = setup(tmp_path, capsys)
    config.write_text(f"provider:\n  name: custom\n  api_key: {SECRET}\n  name: openai\n")
    tty(monkeypatch)
    calls = scripted(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("unexpected confirmation"))
    assert main(editor_args(store, baseline, task, config, budget)) == 1
    captured = capsys.readouterr()
    assert "invalid campaign configuration" in captured.err
    assert SECRET not in captured.out + captured.err
    assert not calls and DurableBudget(store, budget).snapshot().model_calls == 0


def test_config_symlink_and_oversize_file_refused_before_model(tmp_path, monkeypatch, capsys):
    store, _, baseline, _, task, config, _, _, budget, _ = setup(tmp_path, capsys)
    tty(monkeypatch)
    calls = scripted(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("unexpected confirmation"))
    target = config.with_name("link.yaml")
    target.symlink_to(config)
    assert main(editor_args(store, baseline, task, target, budget)) == 1
    assert "cannot read input file" in capsys.readouterr().err
    config.write_bytes(b"a" * (64 * 1024 + 1))
    assert main(editor_args(store, baseline, task, config, budget)) == 1
    assert "input file exceeds size limit" in capsys.readouterr().err
    assert not calls and DurableBudget(store, budget).snapshot().model_calls == 0
