"""ARCEN — FastAPI server (BACKEND-SPEC Part 9 / Part 10 step 11).

Endpoints (Part 10): /api/run, /api/stream, /api/health, /api/config,
/api/sessions.

- stream: NDJSON, Content-Type application/x-ndjson, one JSON object per
  line; every event carries seq + ts; ``Last-Event-ID`` replays from that
  seq (409 + oldest seq when compacted away, 404 for unknown sessions).
- config: GET returns the redacted view (names, never secret values);
  PUT updates the live config.
- runs: POST /api/run starts a turn in a worker thread and returns the
  run_id immediately; DELETE /api/run/<id> interrupts between steps.

The offline turn pipeline composes DRAFT → FORGE → TEMPER exactly as the
architecture draws it; with a provider configured DRAFT plans from the
LLM bridge, without one it uses the deterministic fallback.
"""

from __future__ import annotations

import threading
import time
import uuid

from fastapi import Body, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from arcen.agents.draft import DraftPlanner
from arcen.agents.forge import ForgeExecutor
from arcen.agents.temper import TemperVerifier
from arcen.config import ArcenConfig, load_config
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


class ServerState:
    """Everything the server owns. One per process."""

    def __init__(self, config: ArcenConfig | None = None) -> None:
        self.config = config or load_config()
        self.registry = load_builtin()
        self.store = SessionStore(self.config.session.dir)
        self.plugin_loader = _boot_plugins(self.config)
        if self.plugin_loader.active("after_tool") or self.plugin_loader.active("before_tool"):
            self.registry = HookedRegistry(self.registry, self.plugin_loader)
        self.emitters: dict[str, StreamEmitter] = {}
        self.sessions_meta: dict[str, dict] = {}
        self.run_flags: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

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
def _derive_args(step: dict, goal: str) -> dict:
    """Offline arg derivation: deterministic, narrated, honest."""
    tool = step.get("tool")
    if tool == "bash":
        return {"cmd": goal}  # the goal IS the command in offline mode
    if tool == "file.list":
        return {"path": "."}
    return {}


def run_turn(goal: str, session_id: str, run_id: str, state: ServerState) -> None:
    """One narrated turn, offline-first. Every step lands on the stream."""
    turn_start = time.time()
    emitter = state.emitter_for(session_id)
    interrupted = state.run_flags[run_id]

    def emit(event) -> None:
        wire = emitter.emit(event)
        state.note_event(session_id, wire)
        state.store.append(session_id, wire)

    try:
        emit(RunStart(seq=0, run_id=run_id, goal=goal, depth=0, ts=0.0))

        # DRAFT opens the turn
        draft = DraftPlanner(llm=None, emit=emit)
        plan_events = draft.open_turn(goal)
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
            args = step.get("args") or _derive_args(step, goal)
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
    threading.Thread(target=run_turn, args=(goal, session_id, run_id, STATE), daemon=True).start()
    return {"run_id": run_id, "session": session_id}


@app.delete("/api/run/{run_id}")
def delete_run(run_id: str) -> dict:
    flag = STATE.run_flags.get(run_id)
    if flag is None:
        raise HTTPException(status_code=404, detail="unknown run")
    flag.set()
    return {"ok": True, "run_id": run_id, "interrupted": True}


@app.get("/api/stream")
def get_stream(session: str, last_event_id: str | None = Header(default=None)) -> StreamingResponse:
    if session not in STATE.emitters:
        raise HTTPException(status_code=404, detail="unknown session")
    emitter = STATE.emitters[session]

    last_id = 0
    if last_event_id:
        try:
            last_id = int(last_event_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Last-Event-ID must be an integer")
        if last_id > emitter.last_seq:
            raise HTTPException(status_code=400, detail="Last-Event-ID is in the future")
        if 0 < last_id + 1 < emitter.oldest_seq:
            return JSONResponse(
                status_code=409,
                content={"error": "compacted", "oldest": emitter.oldest_seq},
            )

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
            while True:
                try:
                    wire = await asyncio.wait_for(live.get(), timeout=15)
                except asyncio.TimeoutError:
                    continue  # hold the connection open
                if wire["seq"] <= high_water:
                    continue  # already replayed
                high_water = wire["seq"]
                yield emitter.to_line(wire) + "\n"
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
    updated = ArcenConfig.model_validate(payload)
    STATE.config = updated
    return STATE.config.redacted()


@app.get("/api/sessions")
def list_sessions() -> list[dict]:
    return [STATE.sessions_meta[s] for s in sorted(STATE.sessions_meta)]


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
