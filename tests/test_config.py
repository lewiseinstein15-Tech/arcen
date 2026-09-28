"""T-01 (test plan) — config: loads, validates, defaults, $VAR expansion."""

import warnings

import pytest

from arcen.config import (
    DEFAULT_CONFIG,
    ArcenConfig,
    deep_merge,
    load_config,
    redact_secrets,
    resolve_secrets,
)


def test_missing_file_defaults_with_warning(tmp_path) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        config = load_config(tmp_path / "nope.yaml")
    assert any("CONFIG_DEFAULTED" in str(w.message) or "defaults" in str(w.message).lower() for w in caught)
    assert config.stream.port == 3002
    assert config.subagents.max_depth == 2


def test_yaml_loads_and_merges(tmp_path) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        """
provider:
  models:
    planner: test-planner-model
subagents:
  max_depth: 3
""",
        encoding="utf-8",
    )
    config = load_config(cfg_file)
    assert config.provider.models["planner"] == "test-planner-model"  # overridden
    assert config.provider.models["verifier"] == "claude-haiku-4-5"  # default kept
    assert config.subagents.max_depth == 3


def test_validation_rejects_bad_types(tmp_path) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("stream:\n  port: not-a-port\n", encoding="utf-8")
    with pytest.raises(Exception):
        load_config(cfg_file)


def test_resolve_secrets_expands_from_env(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
    cfg = {"provider": {"api_keys": {"anthropic": "$ANTHROPIC_API_KEY"}}}
    resolved, missing = resolve_secrets(cfg)
    assert resolved["provider"]["api_keys"]["anthropic"] == "sk-test-123"
    assert missing == []


def test_resolve_secrets_missing_marks_degraded(monkeypatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    cfg = {"provider": {"api_keys": {"groq": "$GROQ_API_KEY"}}}
    resolved, missing = resolve_secrets(cfg)
    assert resolved["provider"]["api_keys"]["groq"] == "$GROQ_API_KEY"  # reference kept
    assert missing == ["GROQ_API_KEY"]  # dependent is degraded, boot not aborted


def test_redact_secrets_never_returns_values() -> None:
    cfg = {
        "provider": {"api_keys": {"anthropic": "sk-literal-leak"}},
        "mcps": [{"name": "x", "transport": "http", "url": "u", "headers": {"Authorization": "Bearer leaked"}}],
    }
    view = redact_secrets(cfg)
    assert view["provider"]["api_keys"]["anthropic"] == "<redacted>"
    assert view["mcps"][0]["headers"]["Authorization"] == "<redacted>"


def test_deep_merge_nested() -> None:
    merged = deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"b": 9}})
    assert merged == {"a": {"b": 9, "c": 2}}


def test_full_model_round_trip() -> None:
    model = ArcenConfig.model_validate(DEFAULT_CONFIG)
    assert model.model_dump()["sandbox"]["network"] == "none"


# -- T-038: sandbox.backend field ---------------------------------------------

def test_sandbox_backend_defaults_to_auto() -> None:
    config = ArcenConfig()
    assert config.sandbox.backend == "auto"
    assert DEFAULT_CONFIG["sandbox"]["backend"] == "auto"


def test_sandbox_backend_validated() -> None:
    from pydantic import ValidationError

    ok = ArcenConfig.model_validate({"sandbox": {"backend": "process"}})
    assert ok.sandbox.backend == "process"
    with pytest.raises(ValidationError):
        ArcenConfig.model_validate({"sandbox": {"backend": "swarm"}})
