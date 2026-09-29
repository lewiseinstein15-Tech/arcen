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
  name: custom
  base_url: https://example.invalid/v1
  model: test-model-for-all
agents:
  draft:
    model: test-draft-model
  temper:
    model: test-temper-model
subagents:
  max_depth: 3
""",
        encoding="utf-8",
    )
    config = load_config(cfg_file)
    assert config.provider.name == "custom"  # overridden
    assert config.provider.model == "test-model-for-all"
    assert config.agents.draft.model == "test-draft-model"  # per-agent override
    assert config.agents.forge.model is None  # default kept — inherits
    assert config.agents.temper.model == "test-temper-model"
    assert config.subagents.max_depth == 3


# -- T-049: legacy dict-shape config migrates to the scalar provider --------

def test_legacy_config_migrates_to_scalar_provider(tmp_path) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        """
provider:
  default: custom
  api_keys:
    custom: sk-legacy-key
  base_urls:
    custom: https://legacy.example/v1
  models:
    planner: claude-sonnet-4-5
    executor: claude-sonnet-4-5
    verifier: claude-haiku-4-5
""",
        encoding="utf-8",
    )
    config = load_config(cfg_file)
    assert config.provider.name == "custom"
    assert config.provider.api_key == "sk-legacy-key"
    assert config.provider.base_url == "https://legacy.example/v1"
    # the shipped claude-* role defaults are NOT carried over — the model
    # stays empty (offline) instead of pointing a custom endpoint at anthropic
    assert config.provider.model == ""
    assert config.agents.draft.model is None


def test_legacy_all_equal_model_overrides_become_provider_model(tmp_path) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        """
provider:
  default: custom
  models:
    planner: my-model
    executor: my-model
    verifier: my-model
""",
        encoding="utf-8",
    )
    config = load_config(cfg_file)
    assert config.provider.model == "my-model"
    assert config.agents.draft.model is None  # inherited, not duplicated


def test_legacy_mixed_model_overrides_map_onto_agents(tmp_path) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        """
provider:
  default: custom
  models:
    planner: draft-model-x
    executor: claude-sonnet-4-5
    verifier: verifier-model-x
""",
        encoding="utf-8",
    )
    config = load_config(cfg_file)
    assert config.provider.model == ""
    assert config.agents.draft.model == "draft-model-x"
    assert config.agents.forge.model is None  # the claude seed is dropped
    assert config.agents.temper.model == "verifier-model-x"


def test_no_vendor_defaults_ship_in_the_schema() -> None:
    import json

    dumped = json.dumps(DEFAULT_CONFIG)
    assert "claude" not in dumped  # T-049/T-050: no Anthropic defaults anywhere
    config = ArcenConfig()
    assert config.provider.name == ""
    assert config.provider.model == ""
    assert config.agents.draft.model is None
    assert config.subagents.default_model is None


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
        "provider": {"api_key": "sk-literal-leak", "api_keys": {"anthropic": "sk-dict-leak"}},
        "mcps": [{"name": "x", "transport": "http", "url": "u", "headers": {"Authorization": "Bearer leaked"}}],
    }
    view = redact_secrets(cfg)
    assert view["provider"]["api_key"] == "<redacted>"  # T-049 scalar key too
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
