"""T-014 / Test-plan T-11 (server half) — FastAPI server, real uvicorn.

Proves: /api/health returns 200 with {"ok": true}; a run streams all key
events in order over NDJSON; Last-Event-ID resume re-emits from seq;
v0.1.6 — a valid session that exists nowhere streams 200 + held (never
a 404), a malformed id is 400; config API is redacted.

Runs the actual ASGI server (uvicorn, thread) on 127.0.0.1 and speaks
plain HTTP — the same path as `uvicorn arcen.server.app:app --port 3002`.
"""

import json
import threading
import time
import uuid
from types import SimpleNamespace

import httpx
import pytest
import uvicorn

import arcen.server.app as server_app
from arcen.config import ArcenConfig, default_config_path
from arcen.llm.client import LLMResponse, ProviderError
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
    def __init__(self, config_path) -> None:
        # explicit defaults — the suite must not depend on a real
        # ~/.arcen/config.yaml (a dev machine may configure any provider)
        server_app.STATE = ServerState(config=ArcenConfig())
        # T-054: a PUT in this suite must NEVER reach the user's real
        # config.yaml — the state's config_path points into pytest tmp
        server_app.STATE.config_path = config_path
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
def server(tmp_path):
    with _Server(tmp_path / "config.yaml") as s:
        yield s


@pytest.fixture()
def client(server):
    with httpx.Client(base_url=BASE, timeout=30.0) as c:
        yield c


def _new_session(client: httpx.Client, goal: str) -> str:
    session = str(uuid.uuid4())  # T-052: session ids are uuids (T-045 UI mints uuids)
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


def test_stream_malformed_session_400(client) -> None:
    """v0.1.6: a malformed id is a client bug — 400, the same contract as
    /api/sessions/{id} (T-052). A valid id is NEVER rejected (below)."""
    resp = client.get("/api/stream?session=nope")
    assert resp.status_code == 400
    assert "invalid session id" in resp.json()["detail"]


def test_stream_new_session_is_200_held(client) -> None:
    """v0.1.6 BUG 1: a client-minted uuid with no run yet is an empty
    truth — 200 + held NDJSON, never the 404 the laptop logged six times
    before the first POST /api/run."""
    session = str(uuid.uuid4())
    with client.stream("GET", f"/api/stream?session={session}") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/x-ndjson")
        assert not server_app.STATE.store.exists(session)  # the hold writes nothing


def test_stream_idle_hold_pings(client, monkeypatch) -> None:
    """The held stream stays alive: silence past the ping interval emits
    stream.ping keepalives — proxy/NAT idle timeouts never kill the hold
    mid-wait, and the seq-less frame is invisible to the UI store."""
    monkeypatch.setattr(server_app, "STREAM_PING_INTERVAL", 1.0)
    session = str(uuid.uuid4())
    with client.stream("GET", f"/api/stream?session={session}") as resp:
        assert resp.status_code == 200
        line = next(resp.iter_lines())
        assert json.loads(line)["type"] == "stream.ping"


def test_stream_held_then_run_delivers_live(client) -> None:
    """v0.1.6 BUG 1 end-to-end: a stream opened BEFORE the run attaches
    within a poll tick, then delivers the turn live and closes after
    run.done + stream.done — zero 404s, zero refresh, no missed event."""
    session = str(uuid.uuid4())
    lines: list[str] = []
    reader_err: list[str] = []

    def reader() -> None:
        try:
            with httpx.Client(base_url=BASE, timeout=httpx.Timeout(30.0, read=20.0)) as rc:
                with rc.stream("GET", f"/api/stream?session={session}") as resp:
                    assert resp.status_code == 200
                    for line in resp.iter_lines():
                        lines.append(line)
                        if '"stream.done"' in line:
                            return
        except Exception as exc:  # noqa: BLE001
            reader_err.append(repr(exc))

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    time.sleep(0.6)  # past two attach ticks — held, nothing emitted
    assert not lines, "a held stream must not emit before the run starts"
    resp = client.post("/api/run", json={"goal": "echo held-live", "session": session})
    assert resp.status_code == 200
    thread.join(timeout=15)
    assert not reader_err, reader_err
    events = [json.loads(ln) for ln in lines if ln.strip()]
    kinds = [e["type"] for e in events]
    assert kinds[0] == "run.start"
    assert kinds[-1] == "stream.done" and "run.done" in kinds
    assert "stream.ping" not in kinds  # attached before the slow clock fired


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
    server_app.STATE.config_path = old_state.config_path  # T-054: never the real file
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
    assert "models" not in cfg["provider"]  # T-049: the dict shape is gone
    key = cfg["provider"]["api_key"]
    assert key in ("", "<redacted>") or key.startswith("$"), (
        "secret values must never leave the server"
    )


def test_config_put_round_trip(client) -> None:
    # T-054 guard: the suite's PUTs must never touch the user's real file
    real = default_config_path()
    before = real.read_bytes() if real.exists() else None
    cfg = client.get("/api/config").json()
    cfg["subagents"]["max_depth"] = 3
    resp = client.put("/api/config", json=cfg)
    assert resp.status_code == 200
    assert client.get("/api/config").json()["subagents"]["max_depth"] == 3
    after = real.read_bytes() if real.exists() else None
    assert after == before, "the test suite wrote to the REAL ~/.arcen/config.yaml"


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
    session = str(uuid.uuid4())  # v0.1.6: stream ids are uuids (400 otherwise)
    run = client.post("/api/run", json={"goal": "sleep 5", "session": session}).json()
    time.sleep(0.4)
    resp = client.delete(f"/api/run/{run['run_id']}")
    assert resp.status_code == 200
    events = _stream_until(client, session, want="run.done", limit=300)
    assert events[-1]["type"] == "run.done"
    assert events[-1]["status"] == "interrupted"


# -- T-038: sandbox backend configurability ----------------------------------

def test_sandbox_status_endpoint(client, monkeypatch) -> None:
    """Settings fetches the sandbox picture from here; never raises.

    T-043 extends the T-038 keys with the configured backend, the
    effective selection, and the reason — the boot-log four-liner.
    """
    from arcen.sandbox import runtime as runtime_mod

    monkeypatch.setattr(runtime_mod, "_docker_client", lambda: None)
    status = client.get("/api/sandbox/status").json()
    assert {"docker_available", "image_present", "image"} <= set(status)
    assert {"backend", "effective", "reason", "degraded"} <= set(status)
    assert status["docker_available"] is False
    assert status["effective"] == "process"  # auto default, daemon absent
    assert "no docker daemon" in status["reason"]


# -- T-043: the docker-less machine is explicit and honest --------------------

def test_boot_logs_sandbox_state_lines(caplog, monkeypatch) -> None:
    """Boot prints the four [sandbox] lines — daemon / image / selected /
    reason — so the docker-less machine says so out loud."""
    import logging

    from arcen.sandbox import runtime as runtime_mod

    monkeypatch.setattr(runtime_mod, "_docker_client", lambda: None)
    cfg = ArcenConfig()  # default auto
    with caplog.at_level(logging.INFO, logger="arcen.server"):
        ServerState(config=cfg)
    messages = [r.message for r in caplog.records]
    assert any("[sandbox] docker daemon: absent" in m for m in messages)
    assert any("[sandbox] image " in m and ": absent" in m for m in messages)
    assert any("[sandbox] backend selected: process" in m for m in messages)
    assert any("[sandbox] reason: no docker daemon" in m for m in messages)


def test_run_refuses_when_docker_pinned_but_daemon_absent(client, monkeypatch) -> None:
    """backend=docker + no daemon → a clean 409 BEFORE planning, with the
    fix-it message — never a silent process fallback, never a 500."""
    from arcen.sandbox import runtime as runtime_mod

    monkeypatch.setattr(runtime_mod, "_docker_client", lambda: None)
    server_app.STATE.config.sandbox.backend = "docker"
    session = str(uuid.uuid4())
    try:
        resp = client.post("/api/run", json={"goal": "true", "session": session})
    finally:
        server_app.STATE.config.sandbox.backend = "auto"
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail == (
        "Sandbox backend is set to docker, but no docker daemon is reachable. "
        "Either start docker or change the backend in Settings → Sandbox."
    )
    # nothing was planned: the refusal session stays an empty truth (T-052)
    events = client.get(f"/api/sessions/{session}/events")
    assert events.status_code == 200
    assert events.json() == [], "no session was created for a refused run"


def test_run_allows_auto_when_daemon_absent(client, monkeypatch) -> None:
    """backend=auto + no daemon → the run is accepted and the turn
    executes in the quarantined process backend (the amber path)."""
    from arcen.sandbox import runtime as runtime_mod

    monkeypatch.setattr(runtime_mod, "_docker_client", lambda: None)
    assert server_app.STATE.config.sandbox.backend == "auto"
    resp = client.post("/api/run", json={"goal": "true", "session": "s-auto-process"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["run_id"]


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


# -- T-052: a fresh client-generated session is an empty truth, not a 404 ----

def test_events_for_unknown_uuid_is_200_empty(client) -> None:
    session = str(uuid.uuid4())
    resp = client.get(f"/api/sessions/{session}/events")
    assert resp.status_code == 200
    assert resp.json() == []  # never a 404 for a brand-new id
    # nothing was written to disk by the read
    assert not server_app.STATE.store.exists(session)


def test_events_for_invalid_id_is_400(client) -> None:
    resp = client.get("/api/sessions/not-a-uuid/events")
    assert resp.status_code == 400
    assert "invalid session id" in resp.json()["detail"]


def test_session_detail_unknown_uuid_is_empty_shell(client) -> None:
    session = str(uuid.uuid4())
    resp = client.get(f"/api/sessions/{session}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == session
    assert body["created"] > 0
    assert body["title"] == ""
    assert body["events"] == 0
    assert not server_app.STATE.store.exists(session)  # read-only


def test_session_detail_invalid_id_is_400(client) -> None:
    resp = client.get("/api/sessions/also-not-a-uuid")
    assert resp.status_code == 400


def test_session_detail_known_session_returns_meta(client) -> None:
    session = _new_session(client, "echo meta")
    _stream_until(client, session)
    body = client.get(f"/api/sessions/{session}").json()
    assert body["id"] == session
    assert body["events"] > 0
    assert body["title"] != ""


# -- v0.1.6 BUG 2: the provider's cause lands on the stream and in Settings --

class _DeadProviderLLM:
    """A provider whose every call dies with the spec wire error — what
    Client.complete now raises after its (bounded) retry policy."""

    def is_available(self) -> bool:
        return True

    def complete(self, role, messages, **kwargs):
        raise ProviderError("provider error: 401 invalid api key", status=401)

def test_run_provider_error_event_on_stream(client) -> None:
    """A dead provider must end the turn with run.error carrying the
    provider's cause — never an eternal spinner, never a fake offline
    hello, never a silent swallow."""
    server_app.STATE.llm = _DeadProviderLLM()
    try:
        session = _new_session(client, "hello there")
        events = _stream_until(client, session, want="run.error")
    finally:
        server_app.STATE.llm = _StubProviderLLM()
    kinds = [e["type"] for e in events]
    assert kinds[0] == "run.start"
    assert "run.error" in kinds
    assert "answer" not in kinds, "a provider failure must not be masked by an offline reply"
    err = next(e for e in events if e["type"] == "run.error")
    assert err["code"] == "PROVIDER_ERROR"
    assert err["message"] == "provider error: 401 invalid api key"


def test_run_error_stream_closes_cleanly(client) -> None:
    """run.error is terminal → replay ends with the stream.done sentinel
    (the UI's spinner stops the moment the cause is on screen)."""
    server_app.STATE.llm = _DeadProviderLLM()
    try:
        session = _new_session(client, "echo doomed")
        # wait for the turn to finish, then open a fresh stream: replay+close
        time.sleep(1.0)
        resp = client.get(f"/api/stream?session={session}")
    finally:
        server_app.STATE.llm = _StubProviderLLM()
    assert resp.status_code == 200
    lines = [json.loads(line) for line in resp.text.splitlines() if line.strip()]
    assert lines[-1]["type"] == "stream.done"
    assert any(line["type"] == "run.error" for line in lines)


def test_config_test_surfaces_specific_provider_error(client, monkeypatch) -> None:
    """Spec E: Test Connection shows 'provider error: 401 unauthorized —
    check your API key' in one probe call — no stacked retries."""
    import litellm

    calls: list[int] = []

    def failing_completion(**kwargs):
        calls.append(1)
        exc = RuntimeError("nope")
        exc.status_code = 401  # type: ignore[attr-defined]
        exc.body = {"error": {"message": "invalid api key"}}  # type: ignore[attr-defined]
        raise exc

    monkeypatch.setattr(litellm, "completion", failing_completion)
    resp = client.post(
        "/api/config/test",
        json={"provider": "custom", "model": "m", "base_url": "http://x/v1", "api_key": "sk-bad"},
    )
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "provider error: 401 unauthorized — check your API key"
    assert len(calls) == 1, "the probe is one call — no internal retries"


def test_config_test_probe_disables_internal_retries(client, monkeypatch) -> None:
    """The probe's litellm call carries num_retries=0/max_retries=0 —
    litellm's 10s backoff loop never runs for the button."""
    import litellm

    captured: dict = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="pong"))],
        )

    monkeypatch.setattr(litellm, "completion", fake_completion)
    resp = client.post(
        "/api/config/test",
        json={"provider": "custom", "model": "m", "base_url": "http://x/v1", "api_key": "sk-1"},
    )
    assert resp.json()["ok"] is True
    assert captured["num_retries"] == 0 and captured["max_retries"] == 0


def test_config_test_timeout_names_budget(client, monkeypatch) -> None:
    """A hung probe reports its own budget, not a stack trace."""
    import litellm

    def hanging_completion(**kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(litellm, "completion", hanging_completion)
    resp = client.post(
        "/api/config/test",
        json={"provider": "custom", "model": "m", "base_url": "http://x/v1", "api_key": "sk-1"},
    )
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "provider error: timeout after 15s"
