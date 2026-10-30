"""Manual fixed behavioral canaries; Docker mocked unless explicitly enabled."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys

import litellm
import pytest
from test_harness_comparison import provider
from test_probe_execution import Boundary
from test_probe_model import configured, response
from test_probe_workspace import repository

from arcen.harness import HarnessError, probe_container
from arcen.harness import canary as module
from arcen.harness.canary import CASES, _commands, run_manual_canaries
from arcen.harness.cli import _init
from arcen.harness.durable_budget import DurableBudget
from arcen.harness.lineage import HarnessLineage


def setup(tmp_path):
    store, baseline, candidate, cfg = configured(tmp_path)
    repo, commit = repository(tmp_path)
    cap = DurableBudget.create(
        store, max_trials=4, max_model_calls=16, max_judge_calls=0, admission_seconds=120
    )
    return store, baseline, candidate, cfg, repo, commit, cap


def run(args, **changes):
    store, baseline, candidate, cfg, repo, commit, cap = args
    options = {"repo": repo, "commit": commit, "budget": cap, "reviewed_inputs": True}
    options.update(changes)
    return run_manual_canaries(store, baseline, candidate, cfg, **options)


def test_verifiers_check_exact_regular_file_and_reject_symlinks(tmp_path):
    for case in CASES:
        cmd = _commands(case)
        argv = shlex.split(cmd.verify)
        assert argv[:3] == ["/usr/local/bin/python3", "-I", "-c"]
        output = tmp_path / case.output_file
        script = argv[3].replace("/workspace/" + case.output_file, str(output))

        def check(script=script):
            return subprocess.run([sys.executable, "-I", "-c", script], check=False).returncode

        assert check() == 1
        output.write_bytes(case.expected)
        assert check() == 0
        output.write_bytes(case.expected + b"extra")
        assert check() == 1
        output.unlink()
        target = tmp_path / "target"
        target.write_bytes(case.expected)
        output.symlink_to(target)
        assert check() == 1
        output.unlink()


def test_two_cases_use_one_snapshot_and_four_fresh_mock_containers(tmp_path, monkeypatch):
    args = setup(tmp_path)
    store, baseline, _, _, _, _, cap = args
    adopted = _init(str(store.root))
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    orig = module.snapshot_git_commit
    snapshots = []

    def capture(*a):
        snapshot = orig(*a)
        snapshots.append(snapshot.sha256)
        return snapshot

    monkeypatch.setattr(module, "snapshot_git_commit", capture)
    result = run(args)
    assert result.outcome == "passed" and len(result.findings) == 2
    assert all((f.reference, f.candidate) == ("passed", "passed") for f in result.findings)
    assert len(snapshots) == 1 and result.workspace_sha256 == snapshots[0]
    assert len(calls) == 8 and cap.snapshot().trials == 4
    assert all(bound.closed for bound in Boundary.instances[-4:])
    assert HarnessLineage(store, read_only=True).resolve("refs/heads/adopted") == adopted
    assert baseline != adopted


@pytest.mark.parametrize(
    "fail_on, expected", [(1, "inconclusive"), (2, "regression"), (4, "regression")]
)
def test_verifier_failure_stops_on_first_regression_or_baseline_failure(
    tmp_path, monkeypatch, fail_on, expected
):
    args = setup(tmp_path)
    counter = [0]

    class Fake(Boundary):
        def dispatch(self, name, arguments):
            if arguments["cmd"].startswith("/usr/local/bin/python3 -I -c"):
                counter[0] += 1
                if counter[0] == fail_on:
                    return {
                        "ok": False,
                        "result": {"stdout": "", "stderr": "", "exit": 1},
                        "error": "exit 1",
                    }
            return super().dispatch(name, arguments)

    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Fake)
    calls = provider(monkeypatch)
    report = run(args)
    assert report.outcome == expected and counter[0] == fail_on
    assert len(calls) == 2 * fail_on
    assert args[-1].snapshot().trials == fail_on


def test_unavailable_docker_or_bad_verifier_is_inconclusive(tmp_path, monkeypatch):
    from arcen.sandbox.turn import IsolationUnavailable

    args = setup(tmp_path)
    monkeypatch.setattr(
        probe_container,
        "DockerTurnRegistry",
        lambda *a, **kw: (_ for _ in ()).throw(IsolationUnavailable("private")),
    )
    calls = provider(monkeypatch)
    result = run(args)
    assert result.outcome == "inconclusive" and not calls and "private" not in repr(result)


def test_budget_exhaustion_cannot_produce_pass(tmp_path, monkeypatch):
    args = setup(tmp_path)
    cap = DurableBudget.create(
        args[0], max_trials=2, max_model_calls=16, max_judge_calls=0, admission_seconds=120
    )
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch)
    result = run(args, budget=cap)
    assert result.outcome == "inconclusive" and len(calls) == 4
    assert [(f.reference, f.candidate) for f in result.findings] == [
        ("passed", "passed"),
        ("inconclusive", "not-run"),
    ]
    assert cap.snapshot().trials == 2


def test_review_and_candidate_policy_fail_before_git_or_model(tmp_path, monkeypatch):
    args = setup(tmp_path)
    monkeypatch.setattr(module, "snapshot_git_commit", lambda *a: pytest.fail("unexpected git"))
    calls = provider(monkeypatch)
    with pytest.raises(HarnessError, match="review"):
        run(args, reviewed_inputs=False)
    with pytest.raises(HarnessError):
        run_manual_canaries(
            args[0],
            args[1],
            args[1],
            args[3],
            repo=args[4],
            commit=args[5],
            budget=args[6],
            reviewed_inputs=True,
        )
    assert not calls and args[-1].snapshot().trials == 0


def test_real_docker_canaries_when_explicitly_enabled(tmp_path, monkeypatch):
    if os.environ.get("ARCEN_TEST_DOCKER_ISOLATION") != "1":
        pytest.skip("requires real Docker and sandbox image")
    pytest.importorskip("docker")
    args = setup(tmp_path)
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        if len(calls) % 2:
            return response("CODE")
        text = kwargs["messages"][-1]["content"]
        if ".arcen-canary-number.txt" in text:
            cmd = "printf '42\\n' > .arcen-canary-number.txt"
        else:
            cmd = "printf abc | sha256sum | cut -d ' ' -f 1 > .arcen-canary-sha256.txt"
        return response(json.dumps([{"title": "canary", "tool": "bash", "args": {"cmd": cmd}}]))

    monkeypatch.setattr(litellm, "completion", completion)
    result = run(args)
    assert result.outcome == "passed" and len(result.findings) == 2
    assert len(calls) == 8 and args[-1].snapshot().trials == 4


def test_check_backend_error_is_inconclusive_not_regression(tmp_path, monkeypatch):
    args = setup(tmp_path)

    class Timeout(Boundary):
        def dispatch(self, name, arguments):
            if arguments["cmd"].startswith("/usr/local/bin/python3 -I -c"):
                return {
                    "ok": False,
                    "result": {"stdout": "", "stderr": "", "exit": 124},
                    "error": "timeout",
                }
            return super().dispatch(name, arguments)

    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Timeout)
    provider(monkeypatch)
    result = run(args)
    assert result.outcome == "inconclusive"
    assert [(f.reference, f.candidate) for f in result.findings] == [("inconclusive", "not-run")]
    assert Boundary.instances[-1].closed


def test_strict_cleanup_failure_rejects_even_passing_verifier(tmp_path, monkeypatch):
    args = setup(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    monkeypatch.setattr(Boundary, "fail_close", True)
    provider(monkeypatch)
    result = run(args)
    assert result.outcome == "inconclusive" and result.findings[0].candidate == "not-run"


def test_bad_git_snapshot_refused_without_provider_or_host_fallback(tmp_path, monkeypatch):
    args = setup(tmp_path)
    monkeypatch.setattr(
        probe_container, "DockerTurnRegistry", lambda *a, **kw: pytest.fail("Docker")
    )
    calls = provider(monkeypatch)
    with pytest.raises(HarnessError, match="snapshot"):
        run(args, repo=tmp_path / "missing")
    assert not calls and args[-1].snapshot().trials == 0


def test_provider_error_stops_inconclusive_before_candidate(tmp_path, monkeypatch):
    args = setup(tmp_path)
    monkeypatch.setattr(probe_container, "DockerTurnRegistry", Boundary)
    calls = provider(monkeypatch, fail_at=1)
    result = run(args)
    assert result.outcome == "inconclusive" and len(calls) == 1
    assert result.findings[0].reference == "inconclusive"
    assert result.findings[0].candidate == "not-run"
    assert args[-1].snapshot().trials == 1 and Boundary.instances[-1].closed
