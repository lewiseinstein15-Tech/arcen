"""Known-value defense in depth for paired probes; Docker/provider mocked."""

from __future__ import annotations

import json

import litellm
import pytest
from test_manual_campaign import budget as make_budget
from test_manual_campaign import setup as campaign_setup
from test_probe_execution import Boundary
from test_probe_model import SECRET, configured, response
from test_probe_workspace import repository

from arcen.harness import probe_container
from arcen.harness.comparison import run_reviewed_comparison
from arcen.harness.manual_campaign import run_manual_campaign
from arcen.harness.probe_model import ProbeModelError, bind_probe_model
from arcen.harness.resolver import HarnessError


@pytest.mark.parametrize(
    "values", [["secret"], ("abc",), ("x" * 257,), ("\ud800abc",), ("valid",) * 32]
)
def test_invalid_sensitive_values_fail_before_binding(tmp_path, values):
    store, baseline, candidate, cfg = configured(tmp_path)
    with pytest.raises(HarnessError, match="invalid sensitive"):
        bind_probe_model(
            store, baseline, candidate, "inspect project", cfg, sensitive_values=values
        )


def test_model_input_rejects_extra_values_before_call_and_budget(tmp_path, monkeypatch):
    store, baseline, candidate, cfg = configured(tmp_path)
    extra = "confidential-customer-value-93"
    cap = make_budget()
    monkeypatch.setattr(litellm, "completion", lambda **kw: pytest.fail("provider"))
    with pytest.raises(ProbeModelError):
        bind_probe_model(
            store, baseline, candidate, "inspect " + extra, cfg, sensitive_values=(extra,)
        )
    model = bind_probe_model(
        store, baseline, candidate, "inspect project", cfg, budget=cap, sensitive_values=(extra,)
    )
    with pytest.raises(ProbeModelError):
        model.complete("planner", [{"role": "user", "content": "inspect " + extra}])
    assert model.remaining_calls == 4 and cap.snapshot().model_calls == 0


def test_paired_review_scrubs_known_values_from_model_and_tool_evidence(tmp_path, monkeypatch):
    store, baseline, candidate, cfg = configured(tmp_path)
    repo, commit = repository(tmp_path)
    extra = "sensitive-prefix-" + SECRET + "-sensitive-suffix"

    class RevealingBoundary(Boundary):
        def dispatch(self, name, args):
            result = super().dispatch(name, args)
            result["result"]["stdout"] = "tool: " + extra
            return result

    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        if len(calls) % 2:
            return response("CODE")
        return response(json.dumps([{"title": extra, "tool": "bash", "args": {"cmd": "true"}}]))

    monkeypatch.setattr(litellm, "completion", completion)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", RevealingBoundary)
    judged = []

    def judge(request):
        judged.append(request)
        return '{"winner":"tie","confidence":0.5,"reason":"same"}'

    result = run_reviewed_comparison(
        store,
        baseline,
        candidate,
        "inspect project",
        cfg,
        judge,
        repo=repo,
        commit=commit,
        reviewed_inputs=True,
        reviewed_judge_inputs=True,
        sensitive_values=(extra,),
    )
    assert result.reference.status == result.candidate.status == "ok"
    text = repr(result.reference.events) + repr(result.candidate.events) + repr(judged)
    assert "sensitive-prefix-" not in text and "-sensitive-suffix" not in text
    assert extra not in text and SECRET not in text and "[REDACTED]" in text
    assert len(calls) == 4 and len(judged) == 1


def test_campaign_rejects_known_task_value_before_trials_or_review(tmp_path, monkeypatch):
    store, baseline, candidates, cfg, repo, commit, reviews = campaign_setup(tmp_path)
    extra = "sensitive-customer-value-98"
    cap = make_budget()
    monkeypatch.setattr(litellm, "completion", lambda **kw: pytest.fail("provider"))
    monkeypatch.setattr(
        probe_container, "DockerTurnRegistry", lambda *a, **kw: pytest.fail("docker")
    )
    with pytest.raises(ProbeModelError):
        run_manual_campaign(
            store,
            baseline,
            candidates,
            "inspect " + extra,
            cfg,
            lambda _: pytest.fail("judge"),
            repo=repo,
            commit=commit,
            reviews=reviews,
            budget=cap,
            reviewed_inputs=True,
            reviewed_judge_inputs=True,
            sensitive_values=(extra,),
        )
    assert cap.snapshot().trials == cap.snapshot().model_calls == 0 and reviews.list() == ()


def test_direct_trial_extra_known_value_in_snapshot_is_rejected(tmp_path, monkeypatch):
    from test_probe_snapshot_secrets import commit_text

    from arcen.harness.probe_execution import run_reviewed_probe
    from arcen.harness.probe_hygiene import SensitiveSnapshot

    store, baseline, candidate, cfg = configured(tmp_path)
    repo, _ = repository(tmp_path)
    extra = "sensitive-direct-snapshot-78"
    commit = commit_text(repo, b"data " + extra.encode())
    cap = make_budget()
    monkeypatch.setattr(litellm, "completion", lambda **kw: pytest.fail("provider"))
    monkeypatch.setattr(
        probe_container, "DockerTurnRegistry", lambda *a, **kw: pytest.fail("docker")
    )
    with pytest.raises(SensitiveSnapshot) as exc:
        run_reviewed_probe(
            store,
            baseline,
            candidate,
            "inspect project",
            cfg,
            repo=repo,
            commit=commit,
            reviewed_inputs=True,
            budget=cap,
            sensitive_values=(extra,),
        )
    assert extra not in str(exc.value) and cap.snapshot().trials == 0
