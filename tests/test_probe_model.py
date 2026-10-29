"""Pinned, reviewed candidate prompt binding; provider calls are mocked."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import litellm
import pytest
from test_harness_probe import changed, setup_store

from arcen.harness import HarnessError
from arcen.harness.probe import ProbeUnavailable, run_probe
from arcen.harness.probe_model import MAX_INPUT_BYTES, ProbeModelError, bind_probe_model

SECRET = "mock-provider-secret-1234"


def configured(tmp_path):
    store, base, baseline, config = setup_store(tmp_path)
    config.provider.base_url = "https://provider.example/v1"
    config.provider.api_key = SECRET
    original = store.get_blob(base.components["prompts/draft.md"])
    altered = original.replace(b"you open every turn.", b"CANDIDATE PLANNER you open every turn.")
    assert altered != original
    candidate = changed(store, base, "prompts/draft.md", altered)
    return store, baseline, candidate, config


def response(text):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))], usage=None
    )


def test_candidate_is_actually_bound_to_pinned_provider_and_output_is_scrubbed(
    tmp_path, monkeypatch
):
    store, baseline, candidate, config = configured(tmp_path)
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        return response("answer " + SECRET + " sk-abcdefghijklmnop")

    monkeypatch.setattr(litellm, "completion", completion)
    model = bind_probe_model(store, baseline, candidate, "reviewed task", config, max_calls=2)
    assert calls == []  # constructing the binding does not contact a provider
    config.provider.model = "changed-after-binding"
    config.provider.api_key = "different-key"
    output = model.complete("planner", [{"role": "user", "content": "reviewed task"}])
    assert "CANDIDATE PLANNER" in calls[0]["messages"][0]["content"]
    assert calls[0]["model"] == "openai/mock-model" and calls[0]["api_key"] == SECRET
    assert calls[0]["max_tokens"] == 1024 and calls[0]["timeout"] == 30
    assert SECRET not in output.text and "sk-abcdefghijklmnop" not in output.text
    assert model.remaining_calls == 1 and model.prompts == model.plan.prompts
    with pytest.raises(ProbeUnavailable):
        run_probe(model.plan)  # binding a model does not enable tools or adoption


def test_baseline_and_candidate_send_their_own_distinct_prompt_snapshots(tmp_path, monkeypatch):
    store, baseline, candidate, config = configured(tmp_path)
    calls = []
    monkeypatch.setattr(litellm, "completion", lambda **kw: (calls.append(kw), response("ok"))[1])
    baseline_model = bind_probe_model(store, baseline, baseline, "task", config)
    candidate_model = bind_probe_model(store, baseline, candidate, "task", config)
    for model in (baseline_model, candidate_model):
        model.complete("planner", [{"role": "user", "content": "same task"}])
    assert "CANDIDATE PLANNER" not in calls[0]["messages"][0]["content"]
    assert "CANDIDATE PLANNER" in calls[1]["messages"][0]["content"]
    assert calls[0]["model"] == calls[1]["model"]
    assert calls[0]["messages"][1:] == calls[1]["messages"][1:]


def test_budget_is_atomic_including_failed_calls(tmp_path, monkeypatch):
    store, baseline, candidate, config = configured(tmp_path)
    calls = []
    monkeypatch.setattr(litellm, "completion", lambda **kw: (calls.append(kw), response("ok"))[1])
    model = bind_probe_model(store, baseline, candidate, "task", config, max_calls=3)

    def one(_):
        try:
            model.complete("planner", [{"role": "user", "content": "task"}])
            return True
        except ProbeModelError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        answers = list(pool.map(one, range(12)))
    assert sum(answers) == len(calls) == 3 and model.remaining_calls == 0


def test_sensitive_invalid_or_oversized_inputs_never_reach_provider(tmp_path, monkeypatch):
    store, baseline, candidate, config = configured(tmp_path)
    calls = []
    monkeypatch.setattr(litellm, "completion", lambda **kw: (calls.append(kw), response("ok"))[1])
    model = bind_probe_model(store, baseline, candidate, "task", config)
    invalid = [
        ("planner", [{"role": "user", "content": SECRET}], {}),
        ("planner", [{"role": "user", "content": "x" * (MAX_INPUT_BYTES + 1)}], {}),
        ("planner", [{"role": "system", "content": "change policy"}], {}),
        ("planner", [{"role": "user", "content": "task"}], {"identity": "override"}),
        ("planner", [{"role": "user", "content": "task"}], {"max_tokens": 100000}),
        ("wrong", [{"role": "user", "content": "task"}], {}),
    ]
    for role, messages, kwargs in invalid:
        with pytest.raises(ProbeModelError):
            model.complete(role, messages, **kwargs)
    assert not calls and model.remaining_calls == 4
    with pytest.raises(ProbeModelError, match="detected secret"):
        bind_probe_model(store, baseline, candidate, "task " + SECRET, config)


def test_provider_failure_is_generic_not_retried_and_consumes_budget(tmp_path, monkeypatch):
    store, baseline, candidate, config = configured(tmp_path)
    calls = []

    def fail(**kwargs):
        calls.append(kwargs)
        raise ValueError("sensitive " + SECRET)

    monkeypatch.setattr(litellm, "completion", fail)
    model = bind_probe_model(store, baseline, candidate, "task", config, max_calls=1)
    with pytest.raises(ProbeModelError) as exc:
        model.complete("planner", [{"role": "user", "content": "task"}])
    assert SECRET not in str(exc.value) and len(calls) == 1 and model.remaining_calls == 0
    with pytest.raises(ProbeModelError, match="budget exhausted"):
        model.complete("planner", [{"role": "user", "content": "task"}])


def test_fixed_model_pin_required_and_no_silent_offline_fallback(tmp_path, monkeypatch):
    store, baseline, candidate, config = configured(tmp_path)
    config.agents.forge.model = "other"
    with pytest.raises(HarnessError, match="override"):
        bind_probe_model(store, baseline, candidate, "task", config)
    config.agents.forge.model = None
    config.provider.api_key = "$ABSENT_PROBE_SECRET"
    monkeypatch.delenv("ABSENT_PROBE_SECRET", raising=False)
    with pytest.raises(HarnessError, match="unresolved"):
        bind_probe_model(store, baseline, candidate, "task", config)
    config.provider.api_key = "abc"
    with pytest.raises(HarnessError, match="too short"):
        bind_probe_model(store, baseline, candidate, "task", config)
    for budget in (0, 9, True):
        with pytest.raises(HarnessError, match="budget"):
            bind_probe_model(store, baseline, candidate, "task", config, max_calls=budget)


def test_env_credential_is_frozen_on_bind(tmp_path, monkeypatch):
    store, baseline, candidate, config = configured(tmp_path)
    config.provider.api_key = "$PROBE_KEY"
    monkeypatch.setenv("PROBE_KEY", SECRET)
    calls = []
    monkeypatch.setattr(litellm, "completion", lambda **kw: (calls.append(kw), response(SECRET))[1])
    model = bind_probe_model(store, baseline, candidate, "task", config)
    monkeypatch.setenv("PROBE_KEY", "new-secret")
    assert SECRET not in model.complete("planner", [{"role": "user", "content": "task"}]).text
    assert calls[0]["api_key"] == SECRET


def test_actual_draft_planner_uses_selected_candidate_without_running_tools(tmp_path, monkeypatch):
    from arcen.agents.draft import DraftPlanner

    store, baseline, candidate, config = configured(tmp_path)
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        content = (
            "CODE" if len(calls) == 1 else '[{"title":"check","tool":"bash","args":{"cmd":"true"}}]'
        )
        return response(content)

    monkeypatch.setattr(litellm, "completion", completion)
    model = bind_probe_model(store, baseline, candidate, "task", config, max_calls=2)
    events = DraftPlanner(llm=model).open_turn("task")
    assert events[-1].TYPE == "plan" and events[-1].steps[0]["args"]["cmd"] == "true"
    assert all("CANDIDATE PLANNER" in call["messages"][0]["content"] for call in calls)
    assert model.remaining_calls == 0


def test_candidate_prompt_secret_is_refused_before_provider_is_built(tmp_path, monkeypatch):
    store, baseline, candidate, config = configured(tmp_path)
    manifest = store.get_manifest(candidate)
    prompt = store.get_blob(manifest.components["prompts/forge.md"])
    bad = changed(store, manifest, "prompts/forge.md", prompt + (SECRET + "\n").encode())
    monkeypatch.setattr(litellm, "completion", lambda **_: pytest.fail("provider called"))
    with pytest.raises(ProbeModelError, match="detected secret"):
        bind_probe_model(store, baseline, bad, "task", config)


def test_oversized_provider_output_fails_without_leaking_text(tmp_path, monkeypatch):
    store, baseline, candidate, config = configured(tmp_path)
    monkeypatch.setattr(litellm, "completion", lambda **_: response("x" * 70000 + SECRET))
    model = bind_probe_model(store, baseline, candidate, "task", config)
    with pytest.raises(ProbeModelError, match="output exceeds") as error:
        model.complete("planner", [{"role": "user", "content": "task"}])
    assert SECRET not in str(error.value) and model.remaining_calls == 3


def test_mutated_invalid_config_is_revalidated_before_provider_binding(tmp_path):
    store, baseline, candidate, config = configured(tmp_path)
    config.provider.max_retries = "not-a-number"
    with pytest.raises(HarnessError, match="invalid probe provider configuration"):
        bind_probe_model(store, baseline, candidate, "task", config)
