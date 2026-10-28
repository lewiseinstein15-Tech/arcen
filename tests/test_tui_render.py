"""TUI rendering — every frozen event type must draw without a screen.

The render layer only depends on Rich, so these run headless and skip
cleanly when the optional ``tui`` extra (which pulls Rich) is absent.
"""

from __future__ import annotations

import pytest

pytest.importorskip("rich")

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from arcen.stream.events import (
    Answer,
    Command,
    CommandDone,
    FileDiff,
    Memory,
    Plan,
    PlanUpdate,
    RunDone,
    RunError,
    RunStart,
    Spawn,
    SpawnDone,
    StepFail,
    StepPass,
    Think,
    Usage,
    VerifyStart,
    to_dict,
)
from arcen.tui._legacy import render

console = Console(width=120, record=True)


def _draw(renderable: object) -> str:
    """Render anything Rich can draw and return its plain-text output."""
    console.record = True
    console.print(renderable)
    out = console.export_text()
    console.record = False
    return out


def _sample_events() -> list[dict]:
    """One of every frozen type, built through the real dataclasses."""
    events = [
        RunStart(seq=1, run_id="r-abc123", goal="fix the failing test", depth=0),
        Think(seq=2, agent="DRAFT", text="Read the test first, then the module."),
        Plan(seq=3, agent="DRAFT", steps=[
            {"id": 1, "title": "read failing test", "tool": "file.read"},
            {"id": 2, "title": "run pytest -q", "tool": "bash"},
        ]),
        PlanUpdate(seq=4, agent="DRAFT", reason="test bug found", steps=[
            {"id": 1, "title": "edit assertion", "tool": "file.edit"},
        ]),
        Spawn(seq=5, parent="DRAFT", name="TEST-READER", task="extract assertion", depth=1),
        SpawnDone(seq=6, name="TEST-READER", ok=True, calls=2, duration_s=0.4),
        Command(seq=7, agent="FORGE", step=1, tool="bash", args={"cmd": "pytest -q"}),
        CommandDone(seq=8, step=1, ok=True, result={"stdout": "12 passed"}, duration_s=1.2),
        FileDiff(seq=9, path="tests/test_pay.py",
                 patch="--- a/x\n+++ b/x\n@@\n-assert x == 5\n+assert x == 4"),
        VerifyStart(seq=10, agent="TEMPER", target="tests/"),
        StepPass(seq=11, step=2, checks=["pytest -q  # 12 passed"]),
        StepFail(seq=12, step=2, reason="expected 4 got 5", retry=1),
        Answer(seq=13, text="Fixed the assertion. Suite: 12 passed."),
        Memory(seq=14, op="write", entity="test_pay", fact="turn r-abc: 2 steps"),
        Usage(seq=15, tokens={"input": 100, "output": 50}, cost_usd=0.021),
        RunDone(seq=16, status="ok", steps=2, duration_s=3.4),
        RunError(seq=17, code="PROVIDER_ERROR", message="401 unauthorized"),
    ]
    return [to_dict(e) for e in events]


def test_all_seventeen_events_render():
    events = _sample_events()
    assert len(events) == 17
    for event in events:
        rendered = render.render_event(event, width=120)
        # never a bare list/tuple — RichLog would print its repr
        assert not isinstance(rendered, (list, tuple))
        out = _draw(rendered)
        assert out.strip() != ""
        # no repr leak of Rich internals
        assert "Span(" not in out and "Rule(" not in out


def test_each_type_uses_its_identity_marker():
    """The distinctive glyph/keyword for a few key events is visible."""
    by_type = {e["type"]: e for e in _sample_events()}
    assert "RUN" in _draw(render.render_event(by_type["run.start"]))
    plan_out = _draw(render.render_event(by_type["plan"]))
    assert "read failing test" in plan_out and "[bash]" in plan_out
    cmd_out = _draw(render.render_event(by_type["command"]))
    assert "bash" in cmd_out and "pytest -q" in cmd_out
    done_out = _draw(render.render_event(by_type["command.done"]))
    assert "12 passed" in done_out
    diff_out = _draw(render.render_event(by_type["file.diff"]))
    assert "tests/test_pay.py" in diff_out and "assert x == 4" in diff_out
    answer_out = _draw(render.render_event(by_type["answer"]))
    assert "Fixed the assertion" in answer_out
    run_done = _draw(render.render_event(by_type["run.done"]))
    assert "OK" in run_done
    err = _draw(render.render_event(by_type["run.error"]))
    assert "401 unauthorized" in err and "PROVIDER_ERROR" in err


def test_failed_command_renders_error_body():
    event = to_dict(CommandDone(
        seq=1, step=1, ok=False,
        result={"error": "boom: command not found"}, duration_s=0.1,
    ))
    out = _draw(render.render_event(event))
    assert "boom: command not found" in out


def test_unknown_event_type_is_forward_compatible():
    out = _draw(render.render_event({"seq": 99, "type": "future.event", "ts": 0}))
    assert "future.event" in out


def test_clock_handles_garbage():
    assert render.clock(0) == "--:--:--"
    assert render.clock(float("nan")) == "--:--:--"
    stamped = render.clock(1_700_000_000)
    assert len(stamped) == 8 and stamped.count(":") == 2


def test_compact_truncates_long_payloads():
    short = render._compact({"a": 1})
    assert short == '{"a":1}'
    long = render._compact({"x": "z" * 500}, limit=80)
    assert len(long) <= 80 and long.endswith("…")


def test_sandbox_summary_marks_degraded_process():
    degraded = {
        "backend": "auto", "effective": "process", "docker_available": False,
        "image_present": False, "image": "arcen-sandbox:0.1.0",
        "degraded": True, "reason": "no docker daemon",
    }
    out = _draw(render.render_sandbox(degraded))
    assert "process" in out and "degraded" in out and "no docker daemon" in out

    isolated = dict(degraded, effective="docker", degraded=False,
                    docker_available=True, image_present=True, reason="image local")
    out = _draw(render.render_sandbox(isolated))
    assert "docker" in out and "false" in out


def test_config_summary_keeps_redaction():
    cfg = {
        "provider": {"name": "custom", "model": "deepseek-v4", "base_url": "http://x/v1",
                     "api_key": "<redacted>"},
        "agents": {"draft": {"model": None}},
        "sandbox": {"backend": "auto"},
        "mcps": [{"name": "filesystem"}],
        "plugins": {"enabled": ["redact-secrets"]},
    }
    out = _draw(render.render_config(cfg))
    assert "<redacted>" in out and "deepseek-v4" in out
    assert "1 declared" in out and "redact-secrets" in out


def test_welcome_and_error_banners_are_panels():
    assert isinstance(render.welcome("http://127.0.0.1:3002"), Panel)
    banner = render.error_banner("something broke")
    assert isinstance(banner, Panel)
    assert "something broke" in _draw(banner)


def test_long_text_never_escapes_width():
    event = to_dict(Think(seq=1, agent="DRAFT", text="word " * 200))
    rendered = render.render_event(event, width=40)
    assert isinstance(rendered, Text)
    # the RichLog constrains render width to the widget — emulate a 40-col one
    narrow = Console(width=40, record=True)
    narrow.print(rendered)
    for line in narrow.export_text().splitlines():
        assert len(line) <= 40  # fold-overflow guarantees the widget width holds
