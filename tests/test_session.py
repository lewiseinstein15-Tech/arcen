"""T-015 — session store (BACKEND-SPEC Part 2 row 13 / Part 9).

Proves: write event → read back, jsonl format correct, append-only,
resume-from-seq, corrupt-line tolerance, and server integration (every
streamed event lands on disk).
"""

import json
import threading
import time

import httpx
import pytest

from arcen.session.store import SessionStore
from arcen.stream.events import RunStart, Think, to_dict


@pytest.fixture()
def store(tmp_path) -> SessionStore:
    return SessionStore(tmp_path)


def _run_start(seq=1, run_id="r-01J9", goal="fix the failing test"):
    return to_dict(RunStart(seq=seq, run_id=run_id, goal=goal, depth=0, ts=1727500000.0))


def test_write_event_read_back(store) -> None:
    # mirrors the ticket Command: write event, read back
    wire = _run_start()
    store.append("s-01", wire)
    events = store.read("s-01")
    assert events == [wire]
    assert events[0]["type"] == "run.start"
    assert events[0]["seq"] == 1


def test_jsonl_format_correct(store) -> None:
    store.append("s-01", _run_start())
    store.append("s-01", to_dict(Think(seq=2, agent="DRAFT", text="hello", ts=1727500000.1)))
    raw = store.path("s-01").read_text(encoding="utf-8")
    lines = raw.strip().split("\n")
    assert len(lines) == 2
    for line in lines:
        obj = json.loads(line)  # one JSON object per line
        assert set(obj) >= {"seq", "type", "ts"}
    # file ends with a newline (proper NDJSON)
    assert raw.endswith("\n")


def test_append_only_order_preserved(store) -> None:
    for i in range(1, 6):
        store.append("s-01", _run_start(seq=i))
    seqs = [e["seq"] for e in store.read("s-01")]
    assert seqs == [1, 2, 3, 4, 5]
    # rewriting is impossible by construction: append() only opens mode "a"
    store.append("s-01", _run_start(seq=6))
    assert len(store.read("s-01")) == 6


def test_read_from_resume(store) -> None:
    for seq in range(1, 11):
        store.append("s-01", _run_start(seq=seq))
    assert [e["seq"] for e in store.read_from("s-01", 7)] == [8, 9, 10]
    assert store.read_from("s-01", 0) == store.read("s-01")


def test_corrupt_line_skipped_not_fatal(store, tmp_path) -> None:
    store.append("s-01", _run_start(seq=1))
    with open(store.path("s-01"), "a", encoding="utf-8") as fh:
        fh.write("{not json at all\n")
    store.append("s-01", _run_start(seq=2))
    events = store.read("s-01")
    assert len(events) == 2 and events[-1]["seq"] == 2
    assert store._last_skipped == 1


def test_validate_against_frozen_schema(store) -> None:
    store.append("s-01", _run_start(seq=1))
    store.append("s-01", {"seq": 2, "type": "made.up", "ts": 0.0})  # invalid
    valid, invalid = store.validate("s-01")
    assert (valid, invalid) == (1, 1)


def test_list_sessions(store) -> None:
    store.append("s-a", _run_start(seq=1))
    time.sleep(0.01)
    store.append("s-b", _run_start(seq=1))
    rows = store.list()
    assert [r["id"] for r in rows] == ["s-a", "s-b"]
    assert all(r["events"] == 1 for r in rows)


def test_server_persists_every_event(tmp_path) -> None:
    """Server integration: a streamed turn lands in the session jsonl."""
    import uvicorn

    import arcen.server.app as server_app
    from arcen.server.app import ServerState, app

    port = 3181
    server_app.STATE = ServerState()
    server_app.STATE.store = SessionStore(tmp_path)  # type: ignore[attr-defined]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)

    session = "s-disk-test"
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30.0) as client:
        client.post("/api/run", json={"goal": "echo disk", "session": session})
        deadline = time.time() + 20
        while time.time() < deadline:
            events = client.get(f"/api/sessions/{session}/events").json()
            if events and events[-1]["type"] == "run.done":
                break
            time.sleep(0.1)
    server.should_exit = True
    thread.join(timeout=10)

    disk = server_app.STATE.store.read(session)  # type: ignore[attr-defined]
    assert [e["type"] for e in disk][0] == "run.start"
    assert [e["type"] for e in disk][-1] == "run.done"
    valid, invalid = server_app.STATE.store.validate(session)  # type: ignore[attr-defined]
    assert invalid == 0 and valid == len(disk)
