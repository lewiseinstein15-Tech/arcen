"""Static tier partition and opt-in inspection, never adoption."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import MappingProxyType

import pytest

import arcen
from arcen.harness import policy
from arcen.harness.cli import _init, main
from arcen.harness.editor import EDITABLE, apply_exact_diff
from arcen.harness.manifest import COMPONENT_PATHS, Manifest
from arcen.harness.policy import AdoptionUnavailable, adopt_candidate, review_candidate
from arcen.harness.resolver import HarnessError
from arcen.harness.store import HarnessStore


def store_fixture(tmp_path):
    root = tmp_path / "store"
    baseline = _init(str(root))
    store = HarnessStore(root)
    return store, baseline, store.get_manifest(baseline)


def make_candidate(store, base, changes, *, pin=None):
    components = dict(base.components)
    for path, data in changes.items():
        components[path] = store.put_blob(data)
    return store.put_manifest(Manifest(1, pin or base.model_pin, MappingProxyType(components)))


def bytes_on_disk(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def run_inspect(store, identifier, *extra):
    return main(["--store", str(store.root), "inspect", identifier, *extra])


@pytest.mark.parametrize("path", sorted(COMPONENT_PATHS))
def test_every_shipped_path_has_exact_tier_and_adoption_stays_disabled(tmp_path, path):
    store, baseline, base = store_fixture(tmp_path)
    membership = [
        tier
        for tier, paths in enumerate((policy.TIER_0, policy.TIER_1, policy.TIER_2))
        if path in paths
    ]
    assert len(membership) == 1
    if membership == [0]:
        assert path not in EDITABLE
        with pytest.raises(HarnessError, match="not editable"):
            apply_exact_diff(store.get_blob(base.components[path]), path, "bad")
        candidate = make_candidate(store, base, {path: b"changed\n"})
        with pytest.raises(HarnessError, match="protected candidate"):
            review_candidate(store, baseline, candidate)
    else:
        assert path in EDITABLE
        candidate = make_candidate(
            store, base, {path: store.get_blob(base.components[path]) + b"\nMore guidance.\n"}
        )
        result = review_candidate(store, baseline, candidate)
        assert result.changed_paths == (path,) and result.highest_tier == membership[0]
        assert result.human_review_required and not result.adoption_available
    with pytest.raises(AdoptionUnavailable):
        adopt_candidate(store, baseline, candidate)


@pytest.mark.parametrize(
    "case",
    [
        "overlap01",
        "overlap02",
        "overlap12",
        "missing",
        "extra",
        "editable_protected",
        "editable_missing",
        "empty_tier",
        "wrong_type",
        "component_drift",
    ],
)
def test_tier_drift_fails_before_store_access(monkeypatch, case):
    t0, t1, t2 = policy.TIER_0, policy.TIER_1, policy.TIER_2
    if case == "overlap01":
        monkeypatch.setattr(policy, "TIER_1", t1 | {next(iter(t0))})
    if case == "overlap02":
        monkeypatch.setattr(policy, "TIER_2", t2 | {next(iter(t0))})
    if case == "overlap12":
        monkeypatch.setattr(policy, "TIER_2", t2 | {next(iter(t1))})
    if case == "missing":
        monkeypatch.setattr(policy, "TIER_1", frozenset(list(t1)[1:]))
    if case == "extra":
        monkeypatch.setattr(policy, "TIER_1", t1 | {"prompts/unclassified.md"})
    if case == "editable_protected":
        monkeypatch.setattr(policy, "EDITABLE", EDITABLE | t0)
    if case == "editable_missing":
        monkeypatch.setattr(policy, "EDITABLE", EDITABLE - t2)
    if case == "empty_tier":
        monkeypatch.setattr(policy, "TIER_2", frozenset())
    if case == "wrong_type":
        monkeypatch.setattr(policy, "TIER_0", set(t0))
    if case == "component_drift":
        monkeypatch.setattr(policy, "COMPONENT_PATHS", COMPONENT_PATHS | {"new.md"})

    class NeverRead:
        def get_manifest(self, identifier):
            pytest.fail("store accessed before tier validation")

    with pytest.raises(HarnessError, match="tier definitions are inconsistent"):
        review_candidate(NeverRead(), "baseline", "candidate")


def test_opt_in_policy_inspection_is_read_only_and_advisory(tmp_path, capsys):
    store, baseline, base = store_fixture(tmp_path)
    changes = {
        path: store.get_blob(base.components[path]) + b"\nExtra guidance.\n"
        for path in ("prompts/forge.md", "tool-guidance.md")
    }
    candidate = make_candidate(store, base, changes)
    before = bytes_on_disk(store.root)
    assert run_inspect(store, candidate, "--static-policy") == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert baseline in output.out and candidate in output.out
    assert "Static policy review: passed for current code-defined checks only." in output.out
    assert "Highest changed tier: 1; human review required." in output.out
    assert "tier 1: prompts/forge.md" in output.out and "tier 2: tool-guidance.md" in output.out
    assert "does not approve execution or authorize adoption" in output.out
    assert "no approval or review record was created" in output.out
    assert "Extra guidance" not in output.out
    assert bytes_on_disk(store.root) == before
    assert not (store.root / "reviews.sqlite3").exists()


def test_plain_inspection_does_not_run_optional_static_policy(tmp_path, monkeypatch, capsys):
    store, _, base = store_fixture(tmp_path)
    candidate = make_candidate(store, base, {"tool-guidance.md": b"invalid but inspectable"})
    monkeypatch.setattr(
        policy, "review_candidate", lambda *a: pytest.fail("unexpected policy check")
    )
    assert run_inspect(store, candidate) == 0
    assert "Static policy review" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "failure", ["protected", "pin", "invalid_prompt", "unchanged", "corrupt", "tier_drift"]
)
def test_policy_rejection_never_prints_partial_report_or_mutates(
    tmp_path, monkeypatch, capsys, failure
):
    store, baseline, base = store_fixture(tmp_path)
    changes = {
        "prompts/forge.md": store.get_blob(base.components["prompts/forge.md"]) + b"\nExtra.\n"
    }
    if failure == "protected":
        changes = {"guardrails/policy.yaml": b"unsafe\n"}
    if failure == "invalid_prompt":
        changes = {"prompts/forge.md": b"invalid\n"}
    pin = "fixed:demo:other" if failure == "pin" else None
    candidate = (
        baseline if failure == "unchanged" else make_candidate(store, base, changes, pin=pin)
    )
    if failure == "corrupt":
        digest = store.get_manifest(candidate).components["prompts/forge.md"]
        (store.objects / digest).write_bytes(b"tampered")
    if failure == "tier_drift":
        monkeypatch.setattr(policy, "TIER_2", frozenset())
    before = bytes_on_disk(store.root)
    assert run_inspect(store, candidate, "--static-policy", "--diff") == 1
    result = capsys.readouterr()
    assert result.out == "" and result.err.startswith("harness:")
    assert bytes_on_disk(store.root) == before


def test_installed_cli_inspection_outside_checkout(tmp_path):
    store, _, base = store_fixture(tmp_path)
    candidate = make_candidate(
        store,
        base,
        {"tool-guidance.md": store.get_blob(base.components["tool-guidance.md"]) + b"\nExtra.\n"},
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(arcen.__file__).resolve().parent.parent)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "arcen.cli",
            "harness",
            "--store",
            str(store.root),
            "inspect",
            candidate,
            "--static-policy",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "Highest changed tier: 2; human review required." in result.stdout
    assert "does not approve execution or authorize adoption" in result.stdout
