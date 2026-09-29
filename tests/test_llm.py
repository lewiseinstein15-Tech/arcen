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

    slash = build_llm_client(_cfg({"name": "custom", "base_url": "https://x/v1", "api_key": "k", "model": "org/model"}))
    assert slash.model_for("planner") == "org/model"  # already namespaced — bare
