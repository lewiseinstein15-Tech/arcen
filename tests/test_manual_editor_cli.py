"""Interactive editor proposals: explicit opt-in, mocked provider, never adopt."""

from __future__ import annotations

import difflib
import json

import litellm
import pytest
from test_manual_cli import setup, tty
from test_probe_model import SECRET, response

from arcen.harness.cli import main
from arcen.harness.durable_budget import DurableBudget
from arcen.harness.lineage import HarnessLineage


def editor_args(store, baseline, task, config, budget_id, k=1):
    return [
        "--store",
        str(store.root),
        "editor",
        "propose",
        "--baseline",
        baseline,
        "--task-file",
        str(task),
        "--config",
        str(config),
        "--budget",
        budget_id,
        "--k",
        str(k),
    ]


def scripted(monkeypatch, fail_at=None):
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        if len(calls) == fail_at:
            raise RuntimeError("provider exception " + SECRET)
        request = json.loads(kwargs["messages"][-1]["content"])
        path = "prompts/draft.md"
        old = request["components"][path]
        edited = old + "\nReviewed " + request["scope"] + " proposal.\n"
        patch = "".join(
            difflib.unified_diff(
                old.splitlines(True),
                edited.splitlines(True),
                fromfile="a/" + path,
                tofile="b/" + path,
            )
        )
        return response(json.dumps({"path": path, "diff": patch}))

    monkeypatch.setattr(litellm, "completion", completion)
    return calls


def test_editor_requests_two_independent_candidates_after_confirmation(
    tmp_path, monkeypatch, capsys
):
    store, adopted, baseline, _, task, config, _, _, budget_id, _ = setup(tmp_path, capsys)
    tty(monkeypatch)
    calls = scripted(monkeypatch)

    def confirm(prompt):
        assert calls == []
        assert prompt == f"Type EDIT {baseline} to start: "
        return f"EDIT {baseline}"

    monkeypatch.setattr("builtins.input", confirm)
    assert main(editor_args(store, baseline, task, config, budget_id)) == 0
    out = capsys.readouterr().out
    assert "Unadopted invariant candidate:" in out and "Unadopted domain candidate:" in out
    assert "No refs moved" in out and SECRET not in out
    assert len(calls) == 2 and DurableBudget(store, budget_id).snapshot().model_calls == 2
    requests = [json.loads(call["messages"][-1]["content"]) for call in calls]
    assert [r["scope"] for r in requests] == ["invariant", "domain"]
    assert requests[0]["components"] == requests[1]["components"]
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted


def test_cancel_and_non_tty_never_contact_provider(tmp_path, monkeypatch, capsys):
    import sys

    store, _, baseline, _, task, config, _, _, budget_id, _ = setup(tmp_path, capsys)
    calls = scripted(monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert main(editor_args(store, baseline, task, config, budget_id)) == 1
    assert "interactive terminal" in capsys.readouterr().err
    tty(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: "cancel")
    assert main(editor_args(store, baseline, task, config, budget_id)) == 1
    assert "cancelled" in capsys.readouterr().err
    assert not calls and DurableBudget(store, budget_id).snapshot().model_calls == 0


def test_bad_budget_k_and_changed_baseline_refuse_before_prompt(tmp_path, monkeypatch, capsys):
    store, _, baseline, candidate, task, config, _, _, budget_id, _ = setup(tmp_path, capsys)
    tty(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("unexpected prompt"))
    calls = scripted(monkeypatch)
    assert main(editor_args(store, baseline, task, config, budget_id, 0)) == 1
    assert "between 1 and 4" in capsys.readouterr().err
    assert main(editor_args(store, candidate, task, config, budget_id)) == 1
    assert "unchanged packaged baseline" in capsys.readouterr().err
    low = DurableBudget.create(
        store, max_trials=1, max_model_calls=1, max_judge_calls=0, admission_seconds=120
    )
    assert main(editor_args(store, baseline, task, config, low.id)) == 1
    assert "sufficient open" in capsys.readouterr().err
    assert not calls and low.snapshot().model_calls == 0


def test_provider_failure_does_not_leak_secret_and_no_generated_candidates(
    tmp_path, monkeypatch, capsys
):
    store, adopted, baseline, _, task, config, _, _, budget_id, _ = setup(tmp_path, capsys)
    before = set(store.objects.iterdir())
    tty(monkeypatch)
    calls = scripted(monkeypatch, fail_at=2)
    monkeypatch.setattr("builtins.input", lambda _: f"EDIT {baseline}")
    assert main(editor_args(store, baseline, task, config, budget_id)) == 1
    output = capsys.readouterr()
    assert "editor generation failed" in output.err and SECRET not in output.err + output.out
    assert "Unadopted invariant candidate" not in output.out
    assert len(calls) == 2 and DurableBudget(store, budget_id).snapshot().model_calls == 2
    assert set(store.objects.iterdir()) == before
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted


def test_malformed_model_output_fails_without_candidate_writes(tmp_path, monkeypatch, capsys):
    store, _, baseline, _, task, config, _, _, budget_id, _ = setup(tmp_path, capsys)
    before = set(store.objects.iterdir())
    tty(monkeypatch)
    monkeypatch.setattr(
        litellm,
        "completion",
        lambda **_: response('{"path":"guardrails/policy.yaml","diff":"bad"}'),
    )
    monkeypatch.setattr("builtins.input", lambda _: f"EDIT {baseline}")
    assert main(editor_args(store, baseline, task, config, budget_id)) == 1
    assert "editor generation failed" in capsys.readouterr().err
    assert DurableBudget(store, budget_id).snapshot().model_calls == 1
    assert set(store.objects.iterdir()) == before


def test_detected_task_secret_rejected_before_confirmation_or_provider(
    tmp_path, monkeypatch, capsys
):
    store, _, baseline, _, task, config, _, _, budget_id, _ = setup(tmp_path, capsys)
    task.write_text("This task contains " + SECRET)
    tty(monkeypatch)
    calls = scripted(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("confirmation on sensitive task"))
    assert main(editor_args(store, baseline, task, config, budget_id)) == 1
    out = capsys.readouterr()
    assert "model preflight rejected" in out.err and SECRET not in out.err + out.out
    assert not calls and DurableBudget(store, budget_id).snapshot().model_calls == 0


def test_external_stop_between_editor_calls_leaves_no_candidate(tmp_path, monkeypatch, capsys):
    store, _, baseline, _, task, config, _, _, budget_id, _ = setup(tmp_path, capsys)
    before = set(store.objects.iterdir())
    tty(monkeypatch)
    calls = scripted(monkeypatch)
    original = litellm.completion

    def stop_after_first(**kwargs):
        result = original(**kwargs)
        DurableBudget(store, budget_id).stop()
        return result

    monkeypatch.setattr(litellm, "completion", stop_after_first)
    monkeypatch.setattr("builtins.input", lambda _: f"EDIT {baseline}")
    assert main(editor_args(store, baseline, task, config, budget_id)) == 1
    assert "editor generation failed" in capsys.readouterr().err
    assert len(calls) == 1 and set(store.objects.iterdir()) == before
    assert DurableBudget(store, budget_id).snapshot().model_calls == 1


def test_four_rounds_admit_exactly_eight_model_calls(tmp_path, monkeypatch, capsys):
    store, _, baseline, _, task, config, _, _, _, _ = setup(tmp_path, capsys)
    cap = DurableBudget.create(
        store, max_trials=1, max_model_calls=8, max_judge_calls=0, admission_seconds=120
    )
    tty(monkeypatch)
    calls = scripted(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: f"EDIT {baseline}")
    assert main(editor_args(store, baseline, task, config, cap.id, 4)) == 0
    assert len(calls) == cap.snapshot().model_calls == 8
    assert cap.snapshot().trials == 0 and cap.snapshot().judge_calls == 0
    output = capsys.readouterr().out
    assert output.count("Unadopted invariant candidate:") == 4
    assert output.count("Unadopted domain candidate:") == 4


def test_editor_with_real_local_http_provider_and_no_docker(tmp_path, monkeypatch, capsys):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    store, adopted, baseline, _, task, config, _, _, budget_id, _ = setup(tmp_path, capsys)
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            request = json.loads(payload["messages"][-1]["content"])
            requests.append(request)
            path = "prompts/draft.md"
            original = request["components"][path]
            edited = original + "\nLocal " + request["scope"] + " improvement.\n"
            patch = "".join(
                difflib.unified_diff(
                    original.splitlines(True),
                    edited.splitlines(True),
                    fromfile="a/" + path,
                    tofile="b/" + path,
                )
            )
            body = json.dumps(
                {
                    "id": "local-mock",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "mock-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": json.dumps({"path": path, "diff": patch}),
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    except PermissionError:
        pytest.skip("loopback server unavailable")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config.write_text(
            f"provider:\n  name: custom\n  base_url: http://127.0.0.1:{server.server_port}/v1\n  api_key: {SECRET}\n  model: mock-model\n"
        )
        tty(monkeypatch)

        def confirm(_):
            assert requests == []
            return f"EDIT {baseline}"

        monkeypatch.setattr("builtins.input", confirm)
        assert main(editor_args(store, baseline, task, config, budget_id)) == 0
        out = capsys.readouterr().out
        assert "Unadopted invariant candidate:" in out and "Unadopted domain candidate:" in out
        assert SECRET not in out
        assert [item["scope"] for item in requests] == ["invariant", "domain"]
        assert DurableBudget(store, budget_id).snapshot().model_calls == 2
        assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
