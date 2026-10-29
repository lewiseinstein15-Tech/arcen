"""TUI-09 cards and the frozen event visual vocabulary (adapter comes later)."""
from __future__ import annotations

import pytest

pytest.importorskip("textual")

from rich.console import Console
from rich.text import Text

from arcen.stream.events import EVENT_TYPES
from arcen.tui.app import Footer, Header
from arcen.tui.cards.answer import answer_card
from arcen.tui.cards.command import CommandCard
from arcen.tui.cards.diff import diff_card
from arcen.tui.cards.plan import PlanCard, PlanStep
from arcen.tui.cards.system import error_card, memory_chip, run_marker, spawn_card, spawn_done_card
from arcen.tui.cards.thought import thought_card
from arcen.tui.cards.verify import Check, VerifyCard
from arcen.tui.theme import TOKENS
from arcen.tui.views.rail import RunStateRail


def segments(card):
    return list(Console(width=100, force_terminal=True, color_system="truecolor").render(card))


def text(card):
    return "".join(part.text for part in segments(card))


def color(card, value):
    matches = [part for part in segments(card) if value in part.text and part.style and part.style.color]
    assert matches, f"{value!r} has no color"
    return matches[0].style.color.name.lower()


def test_checklist_pass_fail_and_active_colors():
    card = VerifyCard([Check("1", "imports", "python"), Check("2", "tests", "pytest")])
    card.set_status("1", "pass")
    card.set_status("2", "fail", detail="assertion error")
    view = card.render()
    assert all(x in text(view) for x in ("imports", "tests", "assertion error", "✓", "✕"))
    assert color(view, "✓") == TOKENS["emerald"].lower()
    assert color(view, "✕") == TOKENS["rose"].lower()
    card.set_status("2", "active")
    assert "running…" in text(card.render())
    assert color(card.render(), "◐") == TOKENS["amber"].lower()


def test_checklist_addition_and_invalid_updates_are_safe():
    card = VerifyCard([Check("1", "one")])
    card.add_check(Check("2", "two", status="active"))
    with pytest.raises(ValueError):
        card.add_check(Check("2", "duplicate"))
    with pytest.raises(ValueError):
        card.set_status("1", "bogus")
    with pytest.raises(KeyError):
        card.set_status("missing", "pass")
    assert [x.label for x in card.checks] == ["one", "two"]


def test_answer_supports_markdown_inline_and_untrusted_rich_tags():
    card = answer_card("Fixed **critical** bug in `file.py`; [red] stays literal.")
    rendered = text(card)
    assert "critical" in rendered and "file.py" in rendered and "[red]" in rendered
    assert any("critical" in s.text and s.style and s.style.bold for s in segments(card))


def test_answer_accepts_explicit_rich_text_without_mutating_it():
    body = Text("result", style="bold")
    card = answer_card(body)
    body.append(" later")
    assert "result" in text(card) and "later" not in text(card)


def test_error_displays_literal_code_message_and_hint_in_rose():
    card = error_card("PROVIDER_ERROR", "[red] access denied", "Check your key.")
    assert "PROVIDER_ERROR" in text(card) and "[red] access denied" in text(card)
    assert "Check your key." in text(card)
    assert color(card, "PROVIDER_ERROR") == TOKENS["rose"].lower()


def test_memory_marker_and_subagent_failure():
    assert "recall · user · preference" in text(memory_chip("recall", "user", "preference"))
    assert "run r-1" in text(run_marker("r-1"))
    assert "child" in text(spawn_card("child", "research", "DRAFT", depth=20))
    child = spawn_done_card("child", False, 2, 1.25)
    assert "child · failed · 2 calls · 1.25s" in text(child)
    assert color(child, "failed") == TOKENS["rose"].lower()


# These assert visual components for each event contract, independently of
# transport mapping. The real event-to-view adapter is built in TUI-10.
def test_all_frozen_event_view_cases():
    plan = PlanCard([PlanStep("1", "inspect")])
    verify = VerifyCard([Check("1", "checks")])
    command = CommandCard("ls")
    command.append_output("a.py\n")
    rail = RunStateRail()
    rail.apply_state({"tokens": 100, "cost_usd": 0.01})
    header = Header()
    footer = Footer()
    cases = {
        "run.start": (run_marker("r-1"), "r-1"),
        "think": (thought_card("reason"), "reason"),
        "plan": (plan.render(), "inspect"),
        "spawn": (spawn_card("child", "research", "DRAFT"), "research"),
        "spawn.done": (spawn_done_card("child", True, 1, 0.5), "ok"),
        "command": (command.render(), "ls"),
        "file.diff": (diff_card("a.py", "+change"), "+change"),
        "verify.start": (verify.render(), "checks"),
        "answer": (answer_card("finished"), "finished"),
        "memory": (memory_chip("write", "user", "fact"), "fact"),
        "usage": (rail.render(), "100 / 128,000"),
        "run.error": (error_card("ERR", "broken"), "broken"),
    }
    plan.set_status("1", "done")
    cases["plan.update"] = (plan.render(), "●")
    command.finish(exit_code=0, duration_s=0.5)
    cases["command.done"] = (command.render(), "exit 0")
    verify.set_status("1", "pass")
    cases["step.pass"] = (verify.render(), "✓")
    verify.set_status("1", "fail")
    cases["step.fail"] = (verify.render(), "✕")
    header.set_phase("DONE")
    footer.set_live(False)
    cases["run.done"] = (header.render(), "DONE")
    assert set(cases) == set(EVENT_TYPES)
    for name, (view, expected) in cases.items():
        assert expected in text(view), name
    assert not any(s.style and s.style.blink for s in segments(footer.render()))
