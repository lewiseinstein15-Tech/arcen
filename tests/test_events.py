"""T-003 / Test-plan T-02 — the 17 frozen event types (BACKEND-SPEC Part 9).

Proves: all 17 types serialize → deserialize → byte-identical;
unknown type rejected; shapes match the spec's wire examples.
"""

import pytest

from arcen.stream.events import (
    EVENT_TYPES,
    Event,
    EventError,
    UnknownEventError,
    from_dict,
    from_line,
    to_dict,
    to_line,
)

# One representative event per type — the exact shapes from BACKEND-SPEC
# Part 9's JSON examples (seq/type/ts added per the framing rules).
SAMPLES: dict[str, dict] = {
    "run.start": {"run_id": "r-01J9", "goal": "fix the failing test", "depth": 0},
    "think": {"agent": "DRAFT", "text": "Read the test first, then the module."},
    "plan": {
        "agent": "DRAFT",
        "steps": [{"id": 1, "title": "read failing test", "tool": "file.read"}],
    },
    "plan.update": {
        "agent": "DRAFT",
        "reason": "test bug",
        "steps": [{"id": 1, "title": "edit assertion", "tool": "file.edit"}],
    },
    "spawn": {"parent": "DRAFT", "name": "TEST-READER", "task": "extract assertion", "depth": 1},
    "spawn.done": {"name": "TEST-READER", "ok": True, "calls": 3, "duration_s": 12.4},
    "command": {
        "agent": "FORGE",
        "step": 2,
        "tool": "bash",
        "args": {"cmd": "pytest -q tests/"},
    },
    "command.done": {
        "step": 2,
        "ok": True,
        "result": {"stdout": "12 passed", "exit": 0},
        "duration_s": 3.2,
    },
    "file.diff": {
        "path": "tests/test_pay.py",
        "patch": "--- a/tests/test_pay.py\n+++ b/tests/test_pay.py\n@@ -1 +1 @@",
    },
    "verify.start": {"agent": "TEMPER", "target": "tests/"},
    "step.pass": {"step": 3, "checks": ["pytest -q tests/  # 12 passed"]},
    "step.fail": {"step": 3, "reason": "assert 4 == 5", "retry": 1},
    "answer": {"text": "The test expected 5; calc returns 4. Fixed the assertion."},
    "memory": {
        "op": "write",
        "entity": "calc()",
        "fact": "returns int sum; test_pay had a wrong assertion",
    },
    "usage": {"tokens": {"input": 18432, "output": 1204}, "cost_usd": 0.021},
    "run.done": {"status": "ok", "steps": 3, "duration_s": 6.5},
    "run.error": {"code": "SANDBOX_UNAVAILABLE", "message": "docker daemon not reachable"},
}


def test_seventeen_frozen_types() -> None:
    assert len(EVENT_TYPES) == 17
    assert set(SAMPLES) == set(EVENT_TYPES)


def test_all_types_importable_via_star() -> None:
    # mirrors the ticket Command: python -c "from arcen.stream.events import *"
    import builtins

    ns: dict = {}
    builtins.exec("from arcen.stream.events import *", ns)
    for name in EVENT_TYPES:
        cls_name = "".join(p.capitalize().replace(".", "") for p in name.split("."))
        assert ns.get(cls_name), f"{cls_name} not exported"


@pytest.mark.parametrize("etype", sorted(EVENT_TYPES))
def test_roundtrip_dict_byte_identical(etype: str) -> None:
    payload = SAMPLES[etype]
    wire = {"seq": 1, "type": etype, "ts": 1727500000.0, **payload}
    ev = from_dict(wire)
    assert isinstance(ev, Event)
    out = to_dict(ev)
    assert out == wire  # lossless
    # byte-identical: to_line → from_line → to_line
    line = to_line(ev)
    ev2 = from_line(line)
    assert to_line(ev2) == line


@pytest.mark.parametrize("etype", sorted(EVENT_TYPES))
def test_roundtrip_line_key_order(etype: str) -> None:
    payload = SAMPLES[etype]
    wire = {"seq": 1, "type": etype, "ts": 1727500000.0, **payload}
    line = to_line(from_dict(wire))
    # canonical key order: seq, type, payload..., ts
    assert line.startswith('{"seq":1,"type":"' + etype + '"')
    assert line.endswith(',"ts":1727500000.0}')


def test_unknown_type_rejected() -> None:
    with pytest.raises(UnknownEventError):
        from_dict({"seq": 1, "type": "plan.status", "ts": 0.0})
    with pytest.raises(UnknownEventError):
        from_line('{"seq":1,"type":"run.starts","ts":0.0}')


def test_malformed_line_rejected() -> None:
    with pytest.raises(EventError):
        from_line("{not json")


def test_missing_required_fields_rejected() -> None:
    with pytest.raises(EventError):
        from_dict({"seq": 1, "type": "run.start", "ts": 0.0})  # no run_id/goal
    with pytest.raises(EventError):
        from_dict({"type": "think"})  # no seq
    with pytest.raises(EventError):
        from_dict({"seq": 1, "type": "answer", "text": "x", "ts": 0.0, "extra": 1})


def test_line_parse_to_line_is_stable() -> None:
    line = '{"seq":7,"type":"command","agent":"FORGE","step":2,"tool":"bash","args":{"cmd":"pytest -q tests/"},"ts":1727500002.0}'
    ev = from_line(line)
    assert ev.agent == "FORGE"
    assert ev.args == {"cmd": "pytest -q tests/"}
    assert to_line(ev) == line
