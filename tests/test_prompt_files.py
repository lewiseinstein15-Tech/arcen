"""H-02 golden prompt compatibility and fail-closed harness resolution."""

from __future__ import annotations

import json
import shutil
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest
from prompt_capture import capture_prompt_payloads

from arcen.agents.draft import DraftPlanner
from arcen.harness import HarnessError, HarnessResolver, default_prompts
from arcen.llm.client import Client

ROOT = Path(__file__).resolve().parents[1]


def copied_harness(tmp_path):
    shutil.copytree(ROOT / "src/arcen/prompts", tmp_path / "prompts")
    shutil.copyfile(ROOT / "src/arcen/tool-guidance.md", tmp_path / "tool-guidance.md")
    return tmp_path


def test_pre_externalization_provider_payloads_are_byte_identical():
    fixture = ROOT / "tests/fixtures/prompts/H-02-before.json"
    original = json.loads(fixture.read_text(encoding="utf-8"))
    actual = capture_prompt_payloads()
    encode = lambda obj: json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert encode(actual) == encode(original)
    assert len(actual) == 12
    assert {entry["scenario"] for entry in actual} == {
        "code",
        "research",
        "direct",
        "strict_retry",
        "replan",
        "executor",
        "verifier",
    }


def test_bundled_prompts_resolve_and_are_immutable():
    prompts = HarnessResolver().resolve()
    assert prompts == default_prompts()
    assert "{agent}" in prompts.identity_template and prompts.plan.startswith("Return ONLY")
    with pytest.raises(FrozenInstanceError):
        prompts.plan = "changed"


def test_explicit_harness_snapshot_is_used_by_client_and_planner(tmp_path):
    root = copied_harness(tmp_path)
    draft = root / "prompts/draft.md"
    text = draft.read_text(encoding="utf-8")
    text = text.replace("you open every turn.", "CUSTOM JOB.")
    text = text.replace("Classify this user message into one of:", "CUSTOM CLASSIFIER:")
    text = text.replace("Goal: {goal}", "CUSTOM GOAL: {goal}")
    draft.write_text(text, encoding="utf-8")
    prompts = HarnessResolver(root).resolve()
    calls = []

    def complete(**kwargs):
        calls.append(kwargs["messages"])
        text = (
            "CODE" if len(calls) == 1 else '[{"title":"check","tool":"bash","args":{"cmd":"true"}}]'
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )

    client = Client(models={"planner": "mock"}, completion_fn=complete, prompts=prompts)
    DraftPlanner(llm=client).open_turn("run the task")
    assert "CUSTOM JOB." in calls[0][0]["content"]
    assert "CUSTOM CLASSIFIER:" in calls[0][1]["content"]
    assert calls[1][1]["content"].startswith("CUSTOM GOAL: run the task\n")
    # Existing snapshots stay stable; a new resolution sees a later edit.
    draft.write_text(text.replace("CUSTOM JOB.", "NEW JOB."), encoding="utf-8")
    assert prompts.planner_job.startswith("CUSTOM JOB.")
    assert HarnessResolver(root).resolve().planner_job.startswith("NEW JOB.")


@pytest.mark.parametrize("file", ["system.md", "draft.md", "forge.md", "temper.md"])
def test_missing_prompt_is_fatal_no_fallback(tmp_path, file):
    root = copied_harness(tmp_path)
    (root / "prompts" / file).unlink()
    with pytest.raises(HarnessError, match="cannot read prompt"):
        HarnessResolver(root).resolve()


def test_missing_and_duplicate_sections_are_rejected(tmp_path):
    root = copied_harness(tmp_path)
    draft = root / "prompts/draft.md"
    text = draft.read_text(encoding="utf-8")
    draft.write_text(text.replace("## direct\n", "## not-direct\n"), encoding="utf-8")
    with pytest.raises(HarnessError, match="invalid sections"):
        HarnessResolver(root).resolve()
    draft.write_text(text + "## job\nduplicate\n", encoding="utf-8")
    with pytest.raises(HarnessError, match="duplicate section"):
        HarnessResolver(root).resolve()


@pytest.mark.parametrize(
    "bad", ["{agent}", "{agent} {job.__class__}", "{agent} {job!r}", "{agent} {"]
)
def test_invalid_system_templates_fail_closed(tmp_path, bad):
    root = copied_harness(tmp_path)
    (root / "prompts/system.md").write_text(bad + "\n", encoding="utf-8")
    with pytest.raises(HarnessError, match="template"):
        HarnessResolver(root).resolve()


def test_invalid_encoding_and_oversized_files_are_rejected(tmp_path):
    root = copied_harness(tmp_path)
    prompt = root / "prompts/forge.md"
    prompt.write_bytes(b"\xff\n")
    with pytest.raises(HarnessError, match="UTF-8"):
        HarnessResolver(root).resolve()
    prompt.write_bytes(b"x" * (128 * 1024 + 1))
    with pytest.raises(HarnessError, match="exceeds"):
        HarnessResolver(root).resolve()


def test_symlinked_prompt_is_rejected(tmp_path):
    root = copied_harness(tmp_path)
    target = root / "prompts/forge.md"
    target.unlink()
    target.symlink_to(root / "prompts/temper.md")
    with pytest.raises(HarnessError, match="symlink"):
        HarnessResolver(root).resolve()


def test_planner_rejects_mismatched_client_snapshot(tmp_path):
    root = copied_harness(tmp_path)
    path = root / "prompts/forge.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("you execute", "different job: you execute"),
        encoding="utf-8",
    )
    changed = HarnessResolver(root).resolve()
    client = Client(models={"planner": "mock"})
    with pytest.raises(ValueError, match="same prompt snapshot"):
        DraftPlanner(llm=client, prompts=changed)


def test_symlinked_prompt_directory_is_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "prompts").symlink_to(ROOT / "src/arcen/prompts", target_is_directory=True)
    with pytest.raises(HarnessError, match="directory cannot be a symlink"):
        HarnessResolver(root).resolve()


def test_missing_final_newline_is_rejected(tmp_path):
    root = copied_harness(tmp_path)
    path = root / "prompts/system.md"
    path.write_text(path.read_text(encoding="utf-8").rstrip("\n"), encoding="utf-8")
    with pytest.raises(HarnessError, match="LF-terminated"):
        HarnessResolver(root).resolve()


def test_missing_tool_guidance_is_fatal(tmp_path):
    root = copied_harness(tmp_path)
    (root / "tool-guidance.md").unlink()
    with pytest.raises(HarnessError, match="cannot read prompt tool-guidance"):
        HarnessResolver(root).resolve()
