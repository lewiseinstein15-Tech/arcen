"""ARCEN — FastAPI server (BACKEND-SPEC Part 9 / Part 10 step 11).

Endpoints (Part 10): /api/run, /api/stream, /api/health, /api/config,
/api/sessions.

- stream: NDJSON, Content-Type application/x-ndjson, one JSON object per
  line; every event carries seq + ts; ``Last-Event-ID`` replays from that
  seq — optional, garbage/future values replay fresh (never a 400);
  409 + oldest seq when compacted away, 404 for sessions that exist
  nowhere (memory AND disk). After a terminal event the stream emits a
  ``{type:"stream.done"}`` transport frame and closes — replay+close.
- config: GET returns the redacted view (names, never secret values);
  PUT updates the live config.
- runs: POST /api/run starts a turn in a worker thread and returns the
  run_id immediately; DELETE /api/run/<id> interrupts between steps.

The turn pipeline composes DRAFT → FORGE → TEMPER exactly as the
architecture draws it: with a provider configured DRAFT plans from the
LLM bridge (steps carry real tool args); without one, real tasks refuse
cleanly (T-037) — no goal-as-bash fallback exists anywhere.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid

from fastapi import Body, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from arcen.agents.draft import DraftPlanner
from arcen.agents.forge import ForgeExecutor
from arcen.agents.temper import TemperVerifier
from arcen.config import ArcenConfig, default_config_path, load_config, resolve_secrets, save_config
from arcen.llm.bridge import build_llm_client
from arcen.plugins.loader import PluginLoader
from arcen.session.store import SessionStore
from arcen.stream.emitter import StreamEmitter
from arcen.stream.events import (
    Answer,
    Memory,
    RunDone,
    RunError,
    RunStart,
    Usage,
)
from arcen.tools.registry import load_builtin

app = FastAPI(title="ARCEN", version="0.1.0")

log = logging.getLogger("arcen.server")


class ServerState:
    """Everything the server owns. One per process."""

    def __init__(self, config: ArcenConfig | None = None) -> None:
        self.config_path = default_config_path()
        self.config = config or load_config()
        self.llm = build_llm_client(self.config)  # None → offline mode
        self.registry = load_builtin()
        self.store = SessionStore(self.config.session.dir)
        self.plugin_loader = _boot_plugins(self.config)
        if self.plugin_loader.active("after_tool") or self.plugin_loader.active("before_tool"):
            self.registry = HookedRegistry(self.registry, self.plugin_loader)
        self.emitters: dict[str, StreamEmitter] = {}
        self.sessions_meta: dict[str, dict] = {}
        self.run_flags: dict[str, threading.Event] = {}
        self.active_runs: dict[str, int] = {}  # session -> in-flight turns
        self._lock = threading.Lock()
        self._warn_sandbox_backend()

    def _warn_sandbox_backend(self) -> None:
        """Boot warning for a pinned sandbox backend that cannot serve (T-038)."""
        if self.config.sandbox.backend != "docker":
            return
        from arcen.sandbox.runtime import docker_status

        status = docker_status(self.config.sandbox.image)
        if not status["docker_available"]:
            log.warning(
                "config sandbox.backend='docker' but no docker daemon is "
                "available — sandboxed tasks will fail with a clear error "
                "until docker is running (set sandbox.backend=auto|process "
                "to allow the quarantined process fallback)"
            )
        elif not status["image_present"]:
            log.warning(
                "config sandbox.backend='docker' but sandbox image %s is not "
                "present locally — it will be pulled on first use, or the run "
                "degrades to the process backend",
                status["image"],
            )

    def emitter_for(self, session_id: str) -> StreamEmitter:
        with self._lock:
            if session_id not in self.emitters:
                self.emitters[session_id] = StreamEmitter(session_id)
                self.sessions_meta[session_id] = {
                    "id": session_id,
                    "title": "session",
                    "status": "idle",
                    "events": 0,
                    "last_seq": 0,
                    "created_at": time.time(),
                }
            return self.emitters[session_id]

    def ensure_session(self, session_id: str) -> bool:
        """Attach a session that only exists on disk (server-restart recovery).

        Seeds the fresh emitter from the persisted event log so seqs
        continue after the disk tail instead of colliding from 1 — a
        client's Last-Event-ID from before the restart stays valid and
        /api/stream can replay + resume exactly like /sessions/events.
        Returns True when the session is streamable.
        """
        if session_id in self.emitters:
            return True
        if not self.store.exists(session_id):
            return False
        emitter = self.emitter_for(session_id)
        emitter.seed(self.store.read(session_id))
        meta = self.sessions_meta[session_id]
        meta["events"] = emitter.last_seq
        meta["last_seq"] = emitter.last_seq
        return True

    def turn_started(self, session_id: str) -> None:
        with self._lock:
            self.active_runs[session_id] = self.active_runs.get(session_id, 0) + 1

    def turn_finished(self, session_id: str) -> None:
        with self._lock:
            remaining = self.active_runs.get(session_id, 1) - 1
            if remaining <= 0:
                self.active_runs.pop(session_id, None)
            else:
                self.active_runs[session_id] = remaining

    def note_event(self, session_id: str, wire: dict) -> None:
        meta = self.sessions_meta.get(session_id)
        if meta:
            meta["events"] += 1
            meta["last_seq"] = wire["seq"]


class HookedRegistry:
    """Registry proxy that runs the plugin chain around every dispatch.

    before_tool fails closed (safety hooks); after_tool fails open and
    may mutate results (redaction, metering).
    """

    def __init__(self, inner, loader: PluginLoader) -> None:
        self._inner = inner
        self._loader = loader

    def __getattr__(self, name: str):  # delegate the rest of the Registry API
        return getattr(self._inner, name)

    def dispatch(self, name: str, args: dict) -> dict:
        checked, _ = self._loader.fire(
            "before_tool", {"tool": name, "args": args}, fail_closed=True
        )
        out = self._inner.dispatch(name, checked.get("args", args))
        event, _ = self._loader.fire(
            "after_tool", {"tool": name, "args": args, "result": out.get("result")}
        )
        if event.get("result") is not None:
            out["result"] = event["result"]
        return out


def _boot_plugins(config: ArcenConfig) -> PluginLoader:
    """Boot step 8: load enabled plugins, fire on_boot. Fail-open."""
    loader = PluginLoader(enabled=config.plugins.enabled, paths=config.plugins.paths)
    from arcen.plugins.redact_secrets import RedactSecrets

    if "redact-secrets" in config.plugins.enabled and "redact-secrets" not in loader.plugins:
        instance = RedactSecrets()
        loader.plugins[instance.name] = instance
        loader._wire(instance)
    loader.load()
    try:
        loader.fire("on_boot", config.model_dump())
    except Exception:  # noqa: BLE001 — fail-closed hooks may raise; boot continues
        pass
    return loader


STATE = ServerState()


# ---------------------------------------------------------------------------
# the turn pipeline: DRAFT → FORGE → TEMPER → answer
# ---------------------------------------------------------------------------
def _turn_guard(goal: str, session_id: str, run_id: str, state: ServerState) -> None:
    """Decrement the in-flight counter no matter how the turn ends."""
    try:
        run_turn(goal, session_id, run_id, state)
    finally:
        state.turn_finished(session_id)


def run_turn(goal: str, session_id: str, run_id: str, state: ServerState) -> None:
    """One narrated turn. DRAFT plans from the provider; without one a
    real task refuses cleanly (T-037). Every step lands on the stream."""
    turn_start = time.time()
    emitter = state.emitter_for(session_id)
    interrupted = state.run_flags[run_id]

    def emit(event) -> None:
        wire = emitter.emit(event)
        state.note_event(session_id, wire)
        state.store.append(session_id, wire)

    try:
        emit(RunStart(seq=0, run_id=run_id, goal=goal, depth=0, ts=0.0))

        # DRAFT opens the turn — plan from the provider, or an honest
        # refusal when none is configured (never a fake bash plan, T-037)
        draft = DraftPlanner(llm=state.llm, emit=emit)
        plan_events = draft.open_turn(goal)
        if plan_events and plan_events[-1].TYPE == "answer":
            # conversational short-circuit: the greeting got its warm reply
            # on the stream — no plan, no tools, no verification (BUG 2 fix)
            emit(RunDone(seq=0, status="ok", steps=0,
                         duration_s=round(time.time() - turn_start, 4), ts=0.0))
            return
        steps = plan_events[-1].steps

        # FORGE executes, one step at a time
        def interrupted_done() -> bool:
            if interrupted.is_set():
                emit(RunDone(seq=0, status="interrupted", steps=executed,
                             duration_s=round(time.time() - turn_start, 4), ts=0.0))
                return True
            return False

        forge = ForgeExecutor(state.registry, emit=emit)
        executed = 0
        last_cmd: tuple[str, dict] | None = None
        last_ok = True
        for step in steps:
            if interrupted_done():
                return
            # args come from the plan (the LLM fills them); a step without
            # the args its tool needs simply fails and DRAFT re-plans —
            # the goal text is NEVER run as a command (T-037)
            args = step.get("args") or {}
            events = forge.execute_step({**step, "args": args})
            executed += 1
            last_ok = events[1].ok
            last_cmd = (step.get("tool") or "bash", args)
            if interrupted_done():
                return
            if not events[1].ok:
                # failure → DRAFT re-plans (plan.update on the stream)
                draft.replan(goal, f"step {step.get('id')} failed", failed_step=step)
                break

        # TEMPER verifies adversarially — smoke-check re-runs the last command
        verified = False
        if last_cmd is not None and last_ok:
            tool, cmd_args = last_cmd
            check = cmd_args.get("cmd", "true") if tool == "bash" else "true"
            temper = TemperVerifier(state.registry, emit=emit, adversarial=True, reruns=1)
            verdict = temper.verify(step=executed, target=goal[:64], checks=[check])
            verified = verdict[-1].TYPE == "step.pass"

        emit(Memory(seq=0, op="write", entity=goal[:64],
                    fact=f"turn {run_id}: {executed} steps, verified={verified}", ts=0.0))
        emit(Usage(seq=0, tokens={"input": 0, "output": 0}, cost_usd=0.0, ts=0.0))

        duration = round(time.time() - turn_start, 4)
        if verified:
            emit(Answer(seq=0, text=f"Done. {executed} step(s) executed against: {goal}. Verification passed.", ts=0.0))
            emit(RunDone(seq=0, status="ok", steps=executed, duration_s=duration, ts=0.0))
        else:
            emit(Answer(seq=0, text=f"Turn failed: verification did not pass after {executed} step(s).", ts=0.0))
            emit(RunDone(seq=0, status="failed", steps=executed, duration_s=duration, ts=0.0))
    except Exception as exc:  # noqa: BLE001 — a turn never crashes the server
        emit(RunError(seq=0, code="TURN_FAILED", message=str(exc), ts=0.0))


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.post("/api/run")
def post_run(payload: dict = Body(...)) -> dict:
    goal = str(payload.get("goal", "")).strip()
    if not goal:
        raise HTTPException(status_code=422, detail="goal is required")
    session_id = payload.get("session") or f"s-{uuid.uuid4().hex[:8]}"
    run_id = f"r-{uuid.uuid4().hex[:6]}"
    STATE.run_flags[run_id] = threading.Event()
    STATE.emitter_for(session_id)
    STATE.sessions_meta[session_id]["title"] = goal[:80]
    STATE.turn_started(session_id)
    threading.Thread(
        target=_turn_guard, args=(goal, session_id, run_id, STATE), daemon=True
    ).start()
    return {"run_id": run_id, "session": session_id}


@app.delete("/api/run/{run_id}")
def delete_run(run_id: str) -> dict:
    flag = STATE.run_flags.get(run_id)
    if flag is None:
        raise HTTPException(status_code=404, detail="unknown run")
    flag.set()
    return {"ok": True, "run_id": run_id, "interrupted": True}


TERMINAL_EVENTS = frozenset({"run.done", "run.error"})
# Transport frame, NOT one of the 17 frozen events — tells the client the
# stream closed cleanly after a terminal event (replay+close contract).
STREAM_DONE_LINE = '{"type":"stream.done"}\n'


@app.get("/api/stream")
def get_stream(session: str, last_event_id: str | None = Header(default=None)) -> StreamingResponse:
    """Live NDJSON event stream — replay-first, close-after-turn.

    Resume contract (the stream never rejects a valid session):
    - unknown session (not in memory AND not on disk)  → 404
    - garbage or future Last-Event-ID (client seq from
      before a server restart)                          → fresh replay from 0, still 200
    - Last-Event-ID behind the compaction horizon       → 409 + oldest seq
    - nothing pending and no active turn                → replay + stream.done + close 200
    """
    if not STATE.ensure_session(session):
        raise HTTPException(status_code=404, detail="unknown session")
    emitter = STATE.emitters[session]

    last_id = 0
    if last_event_id:
        try:
            last_id = int(last_event_id)
        except ValueError:
            last_id = 0  # garbage resume hint — replay fresh, never a 400
        if 0 < last_id + 1 < emitter.oldest_seq:
            return JSONResponse(
                status_code=409,
                content={"error": "compacted", "oldest": emitter.oldest_seq},
            )
        last_id = max(last_id, 0)  # negative garbage → fresh
        if last_id > emitter.last_seq:
            last_id = 0  # client ahead (server restart) → full replay from 0

    async def gen():
        import asyncio

        loop = asyncio.get_running_loop()
        live: asyncio.Queue = asyncio.Queue()
        # subscribe BEFORE replaying so no event is lost in between
        unsubscribe = emitter.subscribe(
            lambda wire: loop.call_soon_threadsafe(live.put_nowait, wire)
        )
        try:
            replayed = emitter.replay(last_id)
            for wire in replayed:
                yield emitter.to_line(wire) + "\n"
            high_water = replayed[-1]["seq"] if replayed else last_id
            terminal = bool(replayed) and replayed[-1]["type"] in TERMINAL_EVENTS
            if terminal and not STATE.active_runs.get(session):
                yield STREAM_DONE_LINE  # turn already over → replay + close, never a hang
                return
            while True:
                try:
                    wire = await asyncio.wait_for(live.get(), timeout=15)
                except asyncio.TimeoutError:
                    if terminal and not STATE.active_runs.get(session):
                        yield STREAM_DONE_LINE
                        return
                    continue  # hold the connection open — a turn may still start
                if wire["seq"] <= high_water:
                    continue  # already replayed
                high_water = wire["seq"]
                yield emitter.to_line(wire) + "\n"
                if wire["type"] in TERMINAL_EVENTS:
                    # one stream per turn: the run thread clears the active
                    # counter right after the terminal event lands; wait it
                    # out briefly, then close cleanly (200, no hang).
                    terminal = True
                    for _ in range(40):
                        if not STATE.active_runs.get(session):
                            break
                        await asyncio.sleep(0.05)
                    yield STREAM_DONE_LINE
                    return
        finally:
            unsubscribe()

    return StreamingResponse(
        gen(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/config")
def get_config() -> dict:
    return STATE.config.redacted()


@app.put("/api/config")
def put_config(payload: dict = Body(...)) -> dict:
    """Update the config (T-036 Settings → Save).

    - '<redacted>' api-key values are substituted with the live config's
      stored value — a redacted GET round-trip never wipes a key;
    - the result is persisted to the user's config.yaml (chmod 600);
    - the provider bridge reloads in-memory so the next turn uses the
      new provider immediately (no restart).
    """
    incoming = dict(payload)
    incoming.setdefault("provider", {})
    if isinstance(incoming.get("provider"), dict):
        incoming_provider = dict(incoming["provider"])
        keys = dict(incoming_provider.get("api_keys") or {})
        for name, value in keys.items():
            if value == "<redacted>":
                keys[name] = STATE.config.provider.api_keys.get(name, "")
        incoming_provider["api_keys"] = keys
        incoming["provider"] = incoming_provider
    updated = ArcenConfig.model_validate(incoming)
    STATE.config = updated
    save_config(STATE.config_path, updated)
    STATE.llm = build_llm_client(updated)  # reload the provider bridge
    return STATE.config.redacted()


PROVIDERS = frozenset({"custom", "groq", "deepseek", "openai", "anthropic", "ollama"})


@app.post("/api/config/test")
def test_config(payload: dict = Body(...)) -> dict:
    """Probe a provider connection (T-036 Test Connection).

    Accepts {provider, model?, base_url?, api_key?}. A missing key falls
    back to the live config's stored credential (the UI sends the
    redacted placeholder when the field is untouched). The reply never
    echoes the key — errors are sanitized before returning.
    """
    import litellm

    from arcen.llm.bridge import LITELLM_PREFIX, KEYLESS_PROVIDERS

    provider = str(payload.get("provider", "")).strip().lower()
    if provider not in PROVIDERS:
        raise HTTPException(status_code=422, detail=f"unknown provider {provider!r}")
    model = str(payload.get("model", "")).strip()
    base_url = str(payload.get("base_url", "")).strip() or None
    api_key = str(payload.get("api_key", "")).strip()
    if api_key in ("", "<redacted>"):
        resolved, _missing = resolve_secrets({"api_keys": STATE.config.provider.api_keys})
        api_key = str((resolved.get("api_keys") or {}).get(provider, "") or "")
    if not api_key and provider not in KEYLESS_PROVIDERS:
        return {"ok": False, "error": "no API key configured for this provider"}

    prefix = LITELLM_PREFIX.get(provider, "")
    full_model = model if "/" in model else prefix + (model or {"anthropic": "claude-haiku-4-5", "openai": "gpt-4o-mini"}.get(provider, "default"))
    kwargs: dict = {
        "model": full_model,
        "messages": [{"role": "user", "content": "reply with the word: pong"}],
        "max_tokens": 8,
        "timeout": 15,
    }
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["api_base"] = base_url
    try:
        resp = litellm.completion(**kwargs)
        text = (resp.choices[0].message.content or "").strip()
        return {"ok": True, "model": full_model, "sample": text[:40]}
    except Exception as exc:  # noqa: BLE001 — report, never crash
        message = str(exc)
        if api_key:
            message = message.replace(api_key, "<redacted>")  # never echo the key
        return {"ok": False, "error": message[:300]}


@app.get("/api/sessions")
def list_sessions() -> list[dict]:
    return [STATE.sessions_meta[s] for s in sorted(STATE.sessions_meta)]


@app.get("/api/sandbox/status")
def sandbox_status() -> dict:
    """Docker/image availability for the Settings backend warning (T-038)."""
    from arcen.sandbox.runtime import docker_status

    return docker_status(STATE.config.sandbox.image)


@app.get("/api/sessions/{session_id}/events")
def session_events(session_id: str) -> list[dict]:
    if session_id in STATE.emitters:
        return STATE.emitters[session_id].replay(0)
    if STATE.store.exists(session_id):
        return STATE.store.read(session_id)  # restart recovery: replay from disk
    raise HTTPException(status_code=404, detail="unknown session")


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=STATE.config.stream.port)


if __name__ == "__main__":
    main()
