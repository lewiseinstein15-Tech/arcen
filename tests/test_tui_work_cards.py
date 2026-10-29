"""TUI-08: data-driven plan, command output and unified diff cards."""
from __future__ import annotations

import pytest

pytest.importorskip("textual")

from rich.console import Console

from arcen.tui.cards.command import CommandCard
from arcen.tui.cards.diff import diff_card
from arcen.tui.cards.plan import PlanCard, PlanStep
from arcen.tui.theme import TOKENS


def render(card):
    console = Console(width=100, force_terminal=True, color_system="truecolor")
    return list(console.render(card))


def plain(card):
    return "".join(s.text for s in render(card))


def color_of(card, text):
    segments = [s for s in render(card) if text in s.text and s.style and s.style.color]
    assert segments, f"no colored segment containing {text!r}"
    return segments[0].style.color.name.lower()


@pytest.fixture
def plan():
    return PlanCard([PlanStep("a", "Read file", "file.read"), PlanStep("b", "Run tests", "pytest")])


def test_plan_renders_all_steps_and_metadata(plan):
    text = plain(plan.render())
    assert all(value in text for value in ("plan · 2 steps", "Read file", "file.read", "Run tests", "pytest"))
    assert text.count("○") == 2


def test_plan_mutation_by_id_and_status_colors(plan):
    plan.set_status("a", "done")
    plan.set_status("b", "fail")
    card = plan.render()
    assert color_of(card, "●") == TOKENS["emerald"].lower()
    assert color_of(card, "✕") == TOKENS["rose"].lower()
    plan.set_status("b", "active")
    assert color_of(plan.render(), "◐") == TOKENS["amber"].lower()


def test_replan_replaces_steps_without_stale_rows(plan):
    plan.replace_steps([PlanStep("c", "Retry", "bash", "active")])
    text = plain(plan.render())
    assert "Retry" in text and "plan · 1 steps" in text
    assert "Read file" not in text and "Run tests" not in text


def test_plan_rejects_bad_inputs_without_partial_mutation(plan):
    before = list(plan.steps)
    with pytest.raises(ValueError):
        plan.replace_steps([PlanStep("a", "one"), PlanStep("a", "two")])
    with pytest.raises(ValueError):
        plan.set_status("a", "unknown")
    with pytest.raises(KeyError):
        plan.set_status("missing", "done")
    assert plan.steps == before


def test_command_streams_partial_lines_and_cursor():
    command = CommandCard("printf hello", "bash")
    command.append_output("hel")
    command.append_output("lo\nsec")
    assert "hello" in plain(command.render())
    assert "sec" in plain(command.render())
    assert "▍" in plain(command.render())
    command.append_output("ond\n")
    assert "second" in plain(command.render())


def test_command_output_cap_counts_hidden_lines():
    command = CommandCard("seq 5", output_limit=2)
    command.append_output("line one\nline two\nline three\nline four\nline five\n")
    output = plain(command.render())
    assert "line one" in output and "line two" in output
    assert "line three" not in output and "… 3 more lines" in output
    command.append_output("line six")
    assert "… 4 more lines" in plain(command.render())


def test_command_success_and_failure_exit_footer_colors():
    good = CommandCard("true")
    good.finish(exit_code=0, duration_s=0.125)
    result = good.render()
    assert "exit 0 · 0.12s" in plain(result) and "▍" not in plain(result)
    assert color_of(result, "exit 0") == TOKENS["emerald"].lower()
    bad = CommandCard("false")
    bad.finish(exit_code=2, duration_s=1.5)
    assert "exit 2 · 1.50s" in plain(bad.render())
    assert color_of(bad.render(), "exit 2") == TOKENS["rose"].lower()
    with pytest.raises(RuntimeError):
        bad.append_output("late")


def test_command_unknown_exit_and_failed_status():
    card = CommandCard("tool", tool="file")
    card.finish(exit_code=None, duration_s=0, ok=False)
    assert "forge · file" in plain(card.render())
    assert color_of(card.render(), "failed") == TOKENS["rose"].lower()


def test_zero_cap_and_invalid_cap():
    command = CommandCard("cmd", output_limit=0)
    command.append_output("one\ntwo")
    assert "… 2 more lines" in plain(command.render())
    with pytest.raises(ValueError):
        CommandCard("cmd", output_limit=-1)


def test_unified_diff_colors_headers_hunks_additions_deletions_and_context():
    card = diff_card("src/a.py", "--- a/src/a.py\n+++ b/src/a.py\n@@ -1 +1 @@\n-old value\n+new value\n context")
    text = plain(card)
    assert all(x in text for x in ("src/a.py", "--- a/", "+++ b/", "@@ -1 +1 @@", "-old value", "+new value", "context"))
    assert color_of(card, "--- a/") == TOKENS["mono"].lower()
    assert color_of(card, "+++ b/") == TOKENS["mono"].lower()
    assert color_of(card, "@@ -1") == TOKENS["cyan"].lower()
    assert color_of(card, "-old value") == TOKENS["rose"].lower()
    assert color_of(card, "+new value") == TOKENS["emerald"].lower()
    assert color_of(card, "context") == TOKENS["muted"].lower()


def test_diff_renders_user_text_literally():
    card = diff_card("[red]file", "+[bold]literal[/]")
    output = plain(card)
    assert "[red]file" in output and "+[bold]literal[/]" in output
