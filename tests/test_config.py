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


# -- T-055: env vars seed empty provider slots on boot -----------------------

import logging  # noqa: E402

from arcen.config import mask_secret, seed_provider_from_env  # noqa: E402

ENV = {
    "ARCEN_MODEL_PROVIDER": "custom",
    "ARCEN_MODEL_BASE_URL": "https://inference.dahl.global/v1",
    "ARCEN_MODEL_API_KEY": "dahl_9f2csecretvaluea71b",
    "ARCEN_MODEL_NAME": "deepseek-ai/DeepSeek-V4-Flash-0731",
}


def _set_env(monkeypatch) -> None:
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)


def _clear_env(monkeypatch) -> None:
    for key in ENV:
        monkeypatch.delenv(key, raising=False)


def test_missing_file_seeds_from_env_and_writes(tmp_path, monkeypatch, caplog) -> None:
    _set_env(monkeypatch)
    cfg_file = tmp_path / "config.yaml"
    with caplog.at_level(logging.INFO, logger="arcen.config"):
        config = load_config(cfg_file)
    assert config.provider.name == "custom"
    assert config.provider.base_url == ENV["ARCEN_MODEL_BASE_URL"]
    assert config.provider.api_key == ENV["ARCEN_MODEL_API_KEY"]
    assert config.provider.model == ENV["ARCEN_MODEL_NAME"]
    # the seeded file exists and carries the same provider block
    assert cfg_file.exists()
    import yaml

    on_disk = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))["provider"]
    assert on_disk["model"] == ENV["ARCEN_MODEL_NAME"]
    assert on_disk["api_key"] == ENV["ARCEN_MODEL_API_KEY"]
    # the boot line records the seed with the key MASKED, never in full
    assert "[config] seeded from env:" in caplog.text
    assert mask_secret(ENV["ARCEN_MODEL_API_KEY"]) in caplog.text
    assert ENV["ARCEN_MODEL_API_KEY"] not in caplog.text


def test_config_values_win_over_env(tmp_path, monkeypatch) -> None:
    _set_env(monkeypatch)
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        """
provider:
  name: custom
  base_url: https://config-wins.example/v1
  model: my-model-from-config
""",
        encoding="utf-8",
    )
    config = load_config(cfg_file)
    # non-empty config slots survive; env fills only the EMPTY api_key
    assert config.provider.base_url == "https://config-wins.example/v1"
    assert config.provider.model == "my-model-from-config"
    assert config.provider.api_key == ENV["ARCEN_MODEL_API_KEY"]
    import yaml

    on_disk = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))["provider"]
    assert on_disk["model"] == "my-model-from-config"  # persisted merge keeps it
    assert on_disk["api_key"] == ENV["ARCEN_MODEL_API_KEY"]


def test_restart_with_full_config_does_not_reseed(tmp_path, monkeypatch, caplog) -> None:
    _set_env(monkeypatch)
    cfg_file = tmp_path / "config.yaml"
    with caplog.at_level(logging.INFO, logger="arcen.config"):
        load_config(cfg_file)
        assert "[config] seeded from env:" in caplog.text
        first = cfg_file.read_bytes()
        caplog.clear()
        load_config(cfg_file)  # restart: the file now has everything
    assert cfg_file.read_bytes() == first  # no rewrite on boot
    assert "seeded from env" not in caplog.text  # config wins, silently


def test_emptied_model_reseeds_only_that_field(tmp_path, monkeypatch) -> None:
    _set_env(monkeypatch)
    cfg_file = tmp_path / "config.yaml"
    load_config(cfg_file)
    import yaml

    doc = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
    kept_key, kept_url = doc["provider"]["api_key"], doc["provider"]["base_url"]
    doc["provider"]["model"] = ""  # the user (or a tool) emptied one field
    cfg_file.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    config = load_config(cfg_file)  # restart → ONLY the empty slot re-seeds
    assert config.provider.model == ENV["ARCEN_MODEL_NAME"]
    assert config.provider.api_key == kept_key  # config values untouched
    assert config.provider.base_url == kept_url


def test_no_env_no_file_writes_nothing(tmp_path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    cfg_file = tmp_path / "config.yaml"
    config = load_config(cfg_file)
    assert not cfg_file.exists()  # no env contribution → the file is never written
    assert config.provider.name == "custom"  # in-memory display default
    assert config.provider.api_key == ""
    assert config.provider.model == ""


def test_mask_secret_never_leaks() -> None:
    assert mask_secret(None) == "<none>"
    assert mask_secret("") == "<none>"
    assert mask_secret("short") == "*****"  # too short to show 4+4
    long = "dahl_9f2csecretvaluea71b"
    assert mask_secret(long) == "dahl...a71b"
    assert long not in mask_secret(long)


def test_seed_provider_from_env_is_pure_slots(monkeypatch) -> None:
    monkeypatch.setenv("ARCEN_MODEL_NAME", "env-model")
    monkeypatch.delenv("ARCEN_MODEL_API_KEY", raising=False)
    raw: dict = {"provider": {"name": "groq", "model": ""}}
    seeded, filled = seed_provider_from_env(raw)
    assert seeded["provider"]["model"] == "env-model"
    assert filled == ["model"]  # name was set → no custom fallback needed
    assert seeded["provider"]["name"] == "groq"  # untouched
