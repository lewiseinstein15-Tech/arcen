"""Offline editor proposal safety and deterministic isolated patch application."""

from __future__ import annotations

import difflib
import json
from pathlib import Path

import pytest

from arcen.harness import HarnessError
from arcen.harness.editor import EDITABLE, apply_exact_diff, propose
from arcen.harness.manifest import default_manifest
from arcen.harness.store import HarnessStore

ROOT = Path(__file__).resolve().parents[1] / "src/arcen"


def setup_store(tmp_path):
    store = HarnessStore(tmp_path / "store")
    manifest = default_manifest()
    for path in manifest.components:
        store.put_blob((ROOT / path).read_bytes())
    return store, store.put_manifest(manifest)


def valid_response(request):
    path = "prompts/forge.md"
    text = request["components"][path]
    edited = text.replace("## job\n", "## job\nCarefully check all results.\n")
    patch = "".join(
        difflib.unified_diff(
            text.splitlines(True), edited.splitlines(True), fromfile="a/" + path, tofile="b/" + path
        )
    )
    return json.dumps({"path": path, "diff": patch})


def test_proposals_are_independent_bounded_and_never_persisted(tmp_path):
    store, base = setup_store(tmp_path)
    before = {p.name for p in store.objects.iterdir()}
    seen = []

    def panel(request):
        seen.append((request["scope"], request["index"]))
        response = valid_response(request)
        request["components"].clear()
        return response

    output = propose(store, base, "Improve careful execution", (panel,), k=2)
    assert seen == [("invariant", 0), ("invariant", 1), ("domain", 0), ("domain", 1)]
    assert len(output) == 4 and all(p.path in EDITABLE for p in output)
    assert all(b"Carefully check all results." in p.after for p in output)
    assert {p.name for p in store.objects.iterdir()} == before
    assert store.get_manifest(base) == default_manifest()


@pytest.mark.parametrize(
    "path",
    [
        "guardrails/policy.yaml",
        "tools/registry.toml",
        "../prompts/draft.md",
        "/etc/passwd",
        "plugins/redact_secrets.py",
    ],
)
def test_immutable_or_unsafe_paths_are_rejected(tmp_path, path):
    store, base = setup_store(tmp_path)
    with pytest.raises(HarnessError, match="not editable"):
        propose(
            store, base, "goal", (lambda request: json.dumps({"path": path, "diff": "garbage"}),)
        )


def test_duplicate_json_unknown_fields_and_bad_k_are_rejected(tmp_path):
    store, base = setup_store(tmp_path)
    with pytest.raises(HarnessError):
        propose(store, base, "goal", (lambda request: '{"path":"x","path":"y","diff":"z"}',))
    with pytest.raises(HarnessError):
        propose(
            store,
            base,
            "goal",
            (lambda request: json.dumps({"path": "x", "diff": "x", "extra": 1}),),
        )
    for k in (0, 6, True):
        with pytest.raises(HarnessError):
            propose(store, base, "goal", (valid_response,), k=k)


def test_exact_patch_checks_headers_context_counts_offsets_and_double_file():
    path = "tool-guidance.md"
    base = b"one\ntwo\nthree\n"
    good = "--- a/tool-guidance.md\n+++ b/tool-guidance.md\n@@ -1,3 +1,3 @@\n one\n-two\n+TWO\n three\n"
    assert apply_exact_diff(base, path, good) == b"one\nTWO\nthree\n"
    variants = [
        good.replace("b/tool-guidance.md", "b/../unsafe"),
        good.replace("-two", "-other"),
        good.replace("-1,3", "-1,2"),
        good.replace("+1,3", "+2,3"),
        good + "--- a/guardrails/policy.yaml\n+++ b/guardrails/policy.yaml\n",
        good.replace("+TWO\n", "+TWO"),
    ]
    for patch in variants:
        with pytest.raises(HarnessError):
            apply_exact_diff(base, path, patch)


def test_edit_must_still_validate_as_complete_prompt_set(tmp_path):
    store, base = setup_store(tmp_path)

    def invalid(request):
        path = "prompts/forge.md"
        text = request["components"][path]
        new = text.replace("## job\n", "## invalid\n")
        diff = "".join(
            difflib.unified_diff(
                text.splitlines(True),
                new.splitlines(True),
                fromfile="a/" + path,
                tofile="b/" + path,
            )
        )
        return json.dumps({"path": path, "diff": diff})

    with pytest.raises(HarnessError):
        propose(store, base, "goal", (invalid,))
