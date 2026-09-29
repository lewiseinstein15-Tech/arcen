"""T-004 / Test-plan T-03 — LLM bridge, mocked provider (BACKEND-SPEC Part 2 #14).

Proves: mocked provider returns a completion; per-role model mapping
honored; identity block present in every call; retries work.
"""

from types import SimpleNamespace

import pytest

from arcen.llm.client import ROLE_AGENTS, Client, LLMResponse, identity_block

# T-049: the Client no longer invents vendor defaults — tests pass the
# models the bridge would have resolved.
_MODELS = {"planner": "m-planner", "executor": "m-executor", "verifier": "m-verifier"}


def _fake_completion(text="ok", prompt_tokens=10, completion_tokens=5):
    calls: list[dict] = []

    def fn(**kwargs):
        calls.append(kwargs)
        if getattr(fn, "fail_first", False) and len(calls) == 1:
            raise RuntimeError("transient provider error")
        resp = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
            usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
        )
        return resp

    fn.calls = calls
    return fn


def test_client_imports() -> None:
    # mirrors the ticket Command
    from arcen.llm.client import Client as C

    assert C is Client


def test_identity_block_present_for_all_roles() -> None:
    for role, agent in ROLE_AGENTS.items():
        block = identity_block(role)
        assert agent in block
        assert "ARCEN" in block
        # every role's identity mentions narrating or its contract
        assert len(block) > 100


def test_identity_block_rejects_unknown_role() -> None:
    with pytest.raises(ValueError):
        identity_block("manager")  # a 4th agent is a spec violation


def test_mocked_provider_returns_completion() -> None:
    fake = _fake_completion(text="the plan")
    client = Client(models=dict(_MODELS), completion_fn=fake)
    resp = client.complete("planner", [{"role": "user", "content": "plan this"}])
    assert isinstance(resp, LLMResponse)
    assert resp.text == "the plan"
    assert resp.tokens == {"input": 10, "output": 5}


def test_per_role_model_mapping_honored() -> None:
    fake = _fake_completion()
    client = Client(
        models={"planner": "m-planner", "executor": "m-executor", "verifier": "m-verifier"},
        completion_fn=fake,
    )
    for role, expected in [("planner", "m-planner"), ("executor", "m-executor"), ("verifier", "m-verifier")]:
        client.complete(role, [{"role": "user", "content": "x"}])
        assert fake.calls[-1]["model"] == expected


def test_identity_block_prepended_as_system() -> None:
    fake = _fake_completion()
    client = Client(models=dict(_MODELS), completion_fn=fake)
    msgs = [{"role": "user", "content": "hello"}]
    client.complete("verifier", msgs)
    sent = fake.calls[-1]["messages"]
    assert sent[0]["role"] == "system"
    assert "TEMPER" in sent[0]["content"]
    assert sent[1] == msgs[0]
    assert msgs == [{"role": "user", "content": "hello"}]  # caller list untouched


def test_retry_on_transient_failure() -> None:
    fake = _fake_completion(text="recovered")
    fake.fail_first = True
    client = Client(models=dict(_MODELS), completion_fn=fake, max_retries=2)
    resp = client.complete("executor", [{"role": "user", "content": "go"}])
    assert resp.text == "recovered"
    assert len(fake.calls) == 2


def test_exhausted_retries_raise() -> None:
    def always_fails(**kwargs):
        raise RuntimeError("provider down")

    client = Client(models=dict(_MODELS), completion_fn=always_fails, max_retries=1)
    with pytest.raises(RuntimeError, match="provider down"):
        client.complete("planner", [{"role": "user", "content": "x"}])


# -- T-049: no vendor defaults — a role with no model is a config error ----

def test_model_for_without_models_raises_not_defaults_to_claude() -> None:
    client = Client(completion_fn=_fake_completion())
    with pytest.raises(ValueError, match="no model configured for role 'planner'"):
        client.model_for("planner")


def test_client_models_required_for_complete() -> None:
    client = Client(completion_fn=_fake_completion())
    with pytest.raises(ValueError, match="no model configured"):
        client.complete("executor", [{"role": "user", "content": "x"}])

# -- T-050: agents inherit provider.model; the bridge prefixes per provider --

from arcen.config import ArcenConfig
from arcen.llm.bridge import build_llm_client, model_for


def _cfg(provider: dict, agents: dict | None = None) -> ArcenConfig:
    return ArcenConfig.model_validate({"provider": provider, "agents": agents or {}})


def test_model_for_inherits_provider_model() -> None:
    cfg = _cfg({"name": "custom", "base_url": "https://x/v1", "api_key": "k", "model": "all-model"})
    assert model_for("draft", cfg) == "all-model"
    assert model_for("forge", cfg) == "all-model"
    assert model_for("temper", cfg) == "all-model"


def test_model_for_agent_override_wins() -> None:
    cfg = _cfg(
        {"name": "custom", "base_url": "https://x/v1", "api_key": "k", "model": "all-model"},
        {"temper": {"model": "verifier-only"}},
    )
    assert model_for("draft", cfg) == "all-model"
    assert model_for("temper", cfg) == "verifier-only"


def test_model_for_nothing_configured_raises() -> None:
    cfg = _cfg({"name": "custom", "base_url": "https://x/v1", "api_key": "k", "model": ""})
    with pytest.raises(ValueError, match="no model configured for agent 'draft'"):
        model_for("draft", cfg)


def test_bridge_prefixes_bare_models_per_provider() -> None:
    cfg = _cfg({"name": "custom", "base_url": "https://x/v1", "api_key": "k", "model": "vendor-model"})
    client = build_llm_client(cfg)
    assert client is not None
    assert client.model_for("planner") == "openai/vendor-model"  # custom → openai/
    assert client.model_for("verifier") == "openai/vendor-model"

    groq = build_llm_client(_cfg({"name": "groq", "api_key": "gsk", "model": "llama-3"}))
    assert groq.model_for("executor") == "groq/llama-3"


# -- T-053: a "/" in a custom-endpoint model id is NOT a litellm vendor hint

def test_custom_endpoint_namespaces_even_slash_models(monkeypatch) -> None:
    """org/model on a custom endpoint must hit the configured api_base via
    the openai/ namespace — unprefixed, LiteLLM guesses the vendor wrong."""
    import litellm

    captured: dict = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        from types import SimpleNamespace

        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )

    monkeypatch.setattr(litellm, "completion", fake_completion)
    cfg = _cfg({"name": "custom", "base_url": "https://dahl.example/v1", "api_key": "sk-1", "model": "deepseek-ai/DeepSeek-V4-Flash-0731"})
    client = build_llm_client(cfg)
    assert client is not None
    assert client.model_for("planner") == "openai/deepseek-ai/DeepSeek-V4-Flash-0731"
    client.complete("planner", [{"role": "user", "content": "x"}])
    assert captured["model"] == "openai/deepseek-ai/DeepSeek-V4-Flash-0731"
    assert captured["api_base"] == "https://dahl.example/v1"


# -- v0.1.6 BUG 2: fail-fast classes, exponential backoff, surfaced cause ----

import openai as _openai
import httpx as _httpx

from arcen.llm.client import (
    NO_RETRY_STATUSES,
    RETRYABLE_STATUSES,
    ProviderError,
    classify_provider_failure,
    format_provider_error,
)


def _status_error(status: int, message: str = "provider said no") -> Exception:
    """A litellm-shaped status exception without litellm's constructor
    quirks — status_code + body is all classify_provider_failure uses."""
    exc = RuntimeError(message)
    exc.status_code = status  # type: ignore[attr-defined]
    exc.body = {"error": {"message": message}}  # type: ignore[attr-defined]
    return exc


def _timeout_error() -> Exception:
    return _openai.APITimeoutError(request=_httpx.Request("POST", "https://prov/v1"))


def test_no_retry_statuses_are_the_spec_four() -> None:
    assert NO_RETRY_STATUSES == frozenset({400, 401, 403, 404})
    assert RETRYABLE_STATUSES == frozenset({429, 500, 502, 503})


def test_401_fails_fast_without_retry() -> None:
    calls: list[int] = []

    def failing(**kwargs):
        calls.append(1)
        raise _status_error(401, "invalid api key")

    client = Client(models=dict(_MODELS), completion_fn=failing, max_retries=3)
    with pytest.raises(ProviderError, match=r"provider error: 401 .*invalid api key"):
        client.complete("planner", [{"role": "user", "content": "x"}])
    assert len(calls) == 1, "a bad key must not be retried"


def test_all_four_permanent_statuses_fail_fast() -> None:
    for status in sorted(NO_RETRY_STATUSES):
        calls: list[int] = []

        def failing(**kwargs):
            calls.append(1)
            raise _status_error(status)

        client = Client(models=dict(_MODELS), completion_fn=failing, max_retries=3)
        with pytest.raises(ProviderError) as err:
            client.complete("planner", [{"role": "user", "content": "x"}])
        assert err.value.status == status
        assert len(calls) == 1, f"status {status} must fail on the first call"


def test_500_retries_three_times_with_exponential_backoff(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("arcen.llm.client.time.sleep", lambda s: sleeps.append(s))
    calls: list[int] = []

    def failing(**kwargs):
        calls.append(1)
        raise _status_error(500, "overloaded")

    client = Client(
        models=dict(_MODELS), completion_fn=failing, max_retries=3, retry_backoff_seconds=1.0
    )
    with pytest.raises(ProviderError) as err:
        client.complete("planner", [{"role": "user", "content": "x"}])
    assert len(calls) == 4, "1 initial call + 3 retries"
    assert sleeps == [1.0, 2.0, 4.0], "exponential backoff 1s, 2s, 4s (spec C)"
    assert str(err.value).startswith("provider error: 500")
    assert "(after 4 attempts)" in str(err.value)


def test_429_recovers_when_transient_clears(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("arcen.llm.client.time.sleep", lambda s: sleeps.append(s))
    calls: list[int] = []

    def flaky(**kwargs):
        calls.append(1)
        if len(calls) <= 2:
            raise _status_error(429, "slow down")
        resp = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="back"))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )
        return resp

    client = Client(models=dict(_MODELS), completion_fn=flaky, max_retries=3)
    resp = client.complete("planner", [{"role": "user", "content": "x"}])
    assert resp.text == "back"
    assert len(calls) == 3 and sleeps == [1.0, 2.0]


def test_timeout_fails_immediately_without_retry() -> None:
    calls: list[int] = []

    def hanging(**kwargs):
        calls.append(1)
        raise _timeout_error()

    client = Client(models=dict(_MODELS), completion_fn=hanging, max_retries=3)
    with pytest.raises(ProviderError, match=r"provider error: timeout after 60s"):
        client.complete("planner", [{"role": "user", "content": "x"}])
    assert len(calls) == 1, "a 60s-burned call is never re-burned (spec D)"


def test_complete_defaults_to_60s_timeout() -> None:
    captured: dict = {}

    def fake(**kwargs):
        captured.update(kwargs)
        resp = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )
        return resp

    client = Client(models=dict(_MODELS), completion_fn=fake)
    client.complete("planner", [{"role": "user", "content": "x"}])
    assert captured["timeout"] == 60  # spec D: the per-call budget


def test_first_failure_recorded_and_surfaced(monkeypatch) -> None:
    """Spec A: the FIRST failure's status + body survive to the final
    error even when the last attempt failed differently."""
    sleeps: list[float] = []
    monkeypatch.setattr("arcen.llm.client.time.sleep", lambda s: sleeps.append(s))
    calls: list[int] = []

    def failing(**kwargs):
        calls.append(1)
        raise _status_error(429, "quota exceeded until midnight")

    client = Client(models=dict(_MODELS), completion_fn=failing, max_retries=1)
    with pytest.raises(ProviderError) as err:
        client.complete("planner", [{"role": "user", "content": "x"}])
    assert "429" in str(err.value) and "quota exceeded until midnight" in str(err.value)


def test_classify_and_format_shapes() -> None:
    assert classify_provider_failure(_status_error(403))[0] == 403
    assert classify_provider_failure(_timeout_error())[2] == "timeout"
    assert classify_provider_failure(RuntimeError("mystery"))[2] == "unknown"
    assert format_provider_error(401, "", "status", use_hint=True) == (
        "provider error: 401 unauthorized — check your API key"
    )
    assert format_provider_error(None, "conn reset by peer", "connection") == (
        "provider error: conn reset by peer"
    )


def test_bridge_disables_litellm_internal_retries() -> None:
    """The bridge must suppress litellm's + the SDK's retry loops — the
    stacked 10s backoffs that hung the UI are never coming back."""
    import litellm as _litellm

    cfg = _cfg({"name": "custom", "base_url": "https://x/v1", "api_key": "k", "model": "m"})
    captured: dict = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )

    original = _litellm.completion
    _litellm.completion = fake_completion
    try:
        client = build_llm_client(cfg)
        assert client is not None
        client.complete("planner", [{"role": "user", "content": "x"}])
    finally:
        _litellm.completion = original
    assert captured["num_retries"] == 0
    assert captured["max_retries"] == 0


def test_bridge_carries_config_retry_policy() -> None:
    cfg = _cfg(
        {
            "name": "custom",
            "base_url": "https://x/v1",
            "api_key": "k",
            "model": "m",
            "max_retries": 5,
            "retry_backoff_seconds": 2.5,
        }
    )
    client = build_llm_client(cfg)
    assert client is not None
    assert client.max_retries == 5
    assert client.retry_backoff_seconds == 2.5
