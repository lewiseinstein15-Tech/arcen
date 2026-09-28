"""T-014 / Test-plan T-11 (server half) — FastAPI server, real uvicorn.

Proves: /api/health returns 200 with {"ok": true}; a run streams all key
events in order over NDJSON; Last-Event-ID resume re-emits from seq;
unknown sessions 404; config API is redacted.

Runs the actual ASGI server (uvicorn, thread) on 127.0.0.1 and speaks
plain HTTP — the same path as `uvicorn arcen.server.app:app --port 3002`.
"""

import json
import time

import httpx
import pytest
import uvicorn

import arcen.server.app as server_app
from arcen.config import ArcenConfig
from arcen.llm.client import LLMResponse
from arcen.server.app import ServerState, app

PORT = 3179
BASE = f"http://127.0.0.1:{PORT}"


class _StubProviderLLM:
    """Stand-in provider for the server tests (T-037).

    Classifies CODE and turns the goal into a real bash command with
    real args — exactly what a real planner LLM does. Server tests must
    exercise the provider path: since T-037 the no-provider path refuses
    cleanly instead of planning.
    """

    def is_available(self) -> bool:
        return True

    def complete(self, role, messages, **kwargs):
        content = messages[-1]["content"]
        if "Return ONLY the word" in content:
            return LLMResponse(text="CODE", model="stub", tokens={"input": 1, "output": 1})
        goal_line = next((ln for ln in content.splitlines() if ln.startswith("Goal: ")), "")
        goal = goal_line[len("Goal: "):].strip() or "true"
        plan = json.dumps(
            [
                {"title": f"run: {goal[:40]}", "tool": "bash", "args": {"cmd": goal}},
                {"title": "checkpoint", "tool": "bash", "args": {"cmd": "true"}},
                {"title": "checkpoint 2", "tool": "bash", "args": {"cmd": "true"}},
            ]
        )
        return LLMResponse(text=plan, model="stub", tokens={"input": 8, "output": 8})


class _Server:
    def __init__(self) -> None:
        # explicit defaults — the suite must not depend on a real
        # ~/.arcen/config.yaml (a dev machine may configure any provider)
        server_app.STATE = ServerState(config=ArcenConfig())
        # T-037: with no provider a real task refuses cleanly, so the
        # server tests run against a stub provider (the provider path)
        server_app.STATE.llm = _StubProviderLLM()
        config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error")
        self.server = uvicorn.Server(config)

    def __enter__(self):
        import threading

        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        deadline = time.time() + 15
        while time.time() < deadline:
            if self.server.started:
                break
            time.sleep(0.05)
        assert self.server.started, "uvicorn did not start"
        return self

    def __exit__(self, *exc) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


@pytest.fixture()
def server():
    with _Server() as s:
        yield s


@pytest.fixture()
def client(server):
    with httpx.Client(base_url=BASE, timeout=30.0) as c:
        yield c


def _new_session(client: httpx.Client, goal: str) -> str:
    session = f"s-{goal.split()[0]}-{time.time_ns() % 100000}"
    resp = client.post("/api/run", json={"goal": goal, "session": session})
    assert resp.status_code == 200, resp.text
    return session


def _stream_until(client: httpx.Client, session: str, want: str = "run.done", last_event_id: int | None = None, limit: int = 300) -> list[dict]:
    headers = {"Last-Event-ID": str(last_event_id)} if last_event_id is not None else {}
    events: list[dict] = []
    with client.stream("GET", f"/api/stream?session={session}", headers=headers) as resp:
        assert resp.status_code == 200
        for line in resp.iter_lines():
            if not line.strip():
                continue
            events.append(json.loads(line))
            if events[-1]["type"] == want or len(events) >= limit:
                break
    return events


def test_health_returns_ok(client) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_unknown_session_404(client) -> None:
    resp = client.get("/api/stream?session=nope")
    assert resp.status_code == 404


def test_run_streams_full_turn_in_order(client) -> None:
    session = _new_session(client, "echo arcen-online")
    events = _stream_until(client, session)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "run.start"
    assert "think" in kinds and "plan" in kinds
    assert "command" in kinds and "command.done" in kinds
    assert "verify.start" in kinds and "step.pass" in kinds
    assert kinds[-1] == "run.done"
    assert events[-1]["status"] == "ok" and events[-1]["steps"] >= 3
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs) and seqs[0] == 1
    # curl-style count: the turn narrates every step
    assert len(events) >= 12


def test_stream_resume_from_last_event_id(client) -> None:
    session = _new_session(client, "echo resume-check")
    events = _stream_until(client, session)
    last_seq = events[-1]["seq"]
    resumed = _stream_until(client, session, last_event_id=2)
    assert resumed[0]["seq"] == 3
    assert resumed[-1]["seq"] == last_seq
    assert [e["seq"] for e in resumed] == list(range(3, last_seq + 1))


def test_stream_future_last_event_id_replays_fresh(client) -> None:
    """Client seq ahead of the server (restart wiped memory) must never 400.

    The exact laptop bug: localStorage carried a Last-Event-ID from a
    previous server process; the route now replays from the top with 200.
    """
    session = _new_session(client, "echo x")
    events = _stream_until(client, session)
    resp = client.get(f"/api/stream?session={session}", headers={"Last-Event-ID": "99999"})
    assert resp.status_code == 200
    lines = [json.loads(line) for line in resp.text.splitlines() if line.strip()]
    assert lines[0]["seq"] == 1  # full replay from the top
    assert lines[-1]["type"] == "stream.done"  # clean close, no hang
    assert [e["seq"] for e in lines[:-1]] == [e["seq"] for e in events]


def test_stream_garbage_last_event_id_replays_fresh(client) -> None:
    session = _new_session(client, "echo y")
    _stream_until(client, session)
    resp = client.get(f"/api/stream?session={session}", headers={"Last-Event-ID": "not-a-number"})
    assert resp.status_code == 200
    lines = [json.loads(line) for line in resp.text.splitlines() if line.strip()]
    assert lines[0]["seq"] == 1
    assert lines[-1]["type"] == "stream.done"


def test_stream_closes_after_turn_with_done_sentinel(client) -> None:
    """One stream per turn: terminal event → stream.done frame → close 200."""
    session = _new_session(client, "echo close-check")
    resp = client.get(f"/api/stream?session={session}")
    assert resp.status_code == 200
    lines = [json.loads(line) for line in resp.text.splitlines() if line.strip()]
    assert lines[-1]["type"] == "stream.done"
    assert lines[-2]["type"] == "run.done"
    assert resp.headers["content-type"].startswith("application/x-ndjson")


def test_stream_disk_seed_after_restart(client, server) -> None:
    """Restart survival: memory wiped, disk log intact.

    A fresh ServerState over the same session dir must (a) stream the
    disk history with 200 + sentinel, (b) continue seqs AFTER the disk
    tail for new turns — never stamp colliding seqs from 1 again.
    """
    session = _new_session(client, "echo restart-proof")
    events = _stream_until(client, session)
    last_seq = events[-1]["seq"]

    old_state = server_app.STATE
    server_app.STATE = ServerState(config=old_state.config)
    server_app.STATE.llm = _StubProviderLLM()  # keep the provider path alive
    try:
        assert session not in server_app.STATE.emitters  # memory wiped
        resp = client.get(f"/api/stream?session={session}")
        assert resp.status_code == 200  # was a hang-prone 404 loop before
        lines = [json.loads(line) for line in resp.text.splitlines() if line.strip()]
        assert lines[-1]["type"] == "stream.done"
        assert [e["seq"] for e in lines[:-1]] == list(range(1, last_seq + 1))

        # a NEW turn continues the seq space — the client dedup keeps them
        client.post("/api/run", json={"goal": "echo after-restart", "session": session})
        resumed = _stream_until(client, session, last_event_id=last_seq)
        assert resumed[0]["seq"] == last_seq + 1
        assert resumed[-1]["type"] == "run.done"
    finally:
        server_app.STATE = old_state


def test_config_get_redacted(client) -> None:
    cfg = client.get("/api/config").json()
    assert cfg["provider"]["models"]["planner"] == "claude-sonnet-4-5"
    for value in cfg["provider"].get("api_keys", {}).values():
        assert value in ("$ANTHROPIC_API_KEY", "$OPENAI_API_KEY", "<redacted>"), (
            "secret values must never leave the server"
        )


def test_config_put_round_trip(client) -> None:
    cfg = client.get("/api/config").json()
    cfg["subagents"]["max_depth"] = 3
    resp = client.put("/api/config", json=cfg)
    assert resp.status_code == 200
    assert client.get("/api/config").json()["subagents"]["max_depth"] == 3


def test_sessions_listed_and_replayable(client) -> None:
    session = _new_session(client, "echo hello")
    _stream_until(client, session)
    sessions = client.get("/api/sessions").json()
    assert session in [s["id"] for s in sessions]
    events = client.get(f"/api/sessions/{session}/events").json()
    assert events[0]["type"] == "run.start"
    assert events[-1]["type"] == "run.done"


def test_run_requires_goal(client) -> None:
    resp = client.post("/api/run", json={"goal": ""})
    assert resp.status_code == 422


def test_run_without_provider_refuses_cleanly(client) -> None:
    """T-037 over HTTP: a real task with no provider → a clean refusal
    on the stream. No plan, no command events, no bash, no replan —
    the laptop's "Turn failed" failure mode is dead."""
    server_app.STATE.llm = None  # simulate an unconfigured provider
    try:
        session = _new_session(client, "build a calculator")
        events = _stream_until(client, session)
    finally:
        server_app.STATE.llm = _StubProviderLLM()
    kinds = [e["type"] for e in events]
    assert kinds[0] == "run.start"
    assert "think" in kinds and "answer" in kinds
    assert "plan" not in kinds and "command" not in kinds
    answer = next(e for e in events if e["type"] == "answer")
    assert "model provider" in answer["text"] and "Settings" in answer["text"]
    assert events[-1]["type"] == "run.done" and events[-1]["status"] == "ok"


def test_interrupt_run(client) -> None:
    session = f"s-interrupt-{time.time_ns() % 100000}"
    run = client.post("/api/run", json={"goal": "sleep 5", "session": session}).json()
    time.sleep(0.4)
    resp = client.delete(f"/api/run/{run['run_id']}")
    assert resp.status_code == 200
    events = _stream_until(client, session, want="run.done", limit=300)
    assert events[-1]["type"] == "run.done"
    assert events[-1]["status"] == "interrupted"


# -- T-038: sandbox backend configurability ----------------------------------

def test_sandbox_status_endpoint(client) -> None:
    """Settings fetches docker/image availability from here; never raises."""
    status = client.get("/api/sandbox/status").json()
    assert set(status) == {"docker_available", "image_present", "image"}
    assert isinstance(status["docker_available"], bool)
    assert isinstance(status["image_present"], bool)


def test_boot_warns_when_docker_pinned_but_unavailable(caplog) -> None:
    """sandbox.backend='docker' with no daemon → the boot logs a warning."""
    import logging

    cfg = ArcenConfig()
    cfg.sandbox.backend = "docker"
    with caplog.at_level(logging.WARNING, logger="arcen.server"):
        ServerState(config=cfg)
    assert any("sandbox.backend='docker'" in r.message for r in caplog.records)


def test_boot_quiet_when_backend_is_auto(caplog) -> None:
    import logging

    cfg = ArcenConfig()  # default auto
    with caplog.at_level(logging.WARNING, logger="arcen.server"):
        ServerState(config=cfg)
    assert not any("sandbox.backend" in r.message for r in caplog.records)


# -- T-040: /api/sessions is the single source of truth for ordering ----------

def test_sessions_sorted_newest_first(client) -> None:
    """created_at DESC — newest first, regardless of session id order."""
    for i, created in ((1, 500.0), (2, 900.0), (3, 100.0)):
        sid = f"s-order-{i}"
        server_app.STATE.emitter_for(sid)
        server_app.STATE.sessions_meta[sid]["created_at"] = created
    sessions = client.get("/api/sessions").json()
    ids = [s["id"] for s in sessions]
    assert ids == ["s-order-2", "s-order-1", "s-order-3"]  # 900 → 500 → 100
    created = [s["created_at"] for s in sessions]
    assert created == sorted(created, reverse=True)
