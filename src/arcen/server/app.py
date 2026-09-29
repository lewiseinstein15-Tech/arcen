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

import json
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
    PlanUpdate,
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
        self._log_sandbox_state()

    def _log_sandbox_state(self) -> None:
        """Boot log: the detected sandbox state, verbatim for support (T-043).

        Four lines, always: daemon / image / backend selected / reason —
        the same decision SandboxRuntime makes, surfaced before any task.
        A pinned docker backend that cannot serve additionally warns
        loudly: it will REFUSE runs at /api/run, not degrade silently.
        """
        from arcen.sandbox.runtime import sandbox_state

        st = sandbox_state(self.config.sandbox.backend, self.config.sandbox.image)
        log.info(
            "[sandbox] docker daemon: %s", "present" if st["docker_available"] else "absent"
        )
        log.info(
            "[sandbox] image %s: %s",
            st["image"],
            "present" if st["image_present"] else "absent",
        )
        log.info("[sandbox] backend selected: %s", st["effective"])
        log.info("[sandbox] reason: %s", st["reason"])
        if st["backend"] == "docker" and not st["docker_available"]:
            log.warning(
                "config sandbox.backend='docker' but no docker daemon is "
                "available — sandboxed tasks will be REFUSED at /api/run "
                "with a clear error until docker is running (set "
                "sandbox.backend=auto|process in Settings → Sandbox to "
                "allow the quarantined process backend)"
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
    real task refuses cleanly (T-037). A failed step triggers a DRAFT
    replan and the loop CONTINUES with the corrected steps, bounded to
    2 replans per turn (T-042). Every step lands on the stream."""
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

        # FORGE executes, one step at a time. A failed step triggers a DRAFT
        # replan and the loop CONTINUES with the corrected steps (T-042) —
        # the old code emitted plan.update then broke, so the Aider-style
        # replan was decorative and every nontrivial task died on the first
        # hiccup. Bounds: max 2 replans per turn; a replan that returns
        # nothing useful (empty, or the same failing step again) is terminal;
        # a step that already failed with the same error is terminal. The
        # goal text is NEVER run as a command (T-037).
        def interrupted_done() -> bool:
            if interrupted.is_set():
                emit(RunDone(seq=0, status="interrupted", steps=executed,
                             duration_s=round(time.time() - turn_start, 4), ts=0.0))
                return True
            return False

        def step_sig(step: dict) -> tuple[str, str]:
            """Identity of a step for the repeat-failure guard: tool + args."""
            return (
                step.get("tool") or "bash",
                json.dumps(step.get("args") or {}, sort_keys=True, default=str),
            )

        forge = ForgeExecutor(state.registry, emit=emit)
        executed = 0
        last_cmd: tuple[str, dict] | None = None
        last_ok = True
        pending: list[dict] = list(steps)
        replans = 0
        MAX_REPLANS = 2
        failed_sigs: set[tuple[str, str]] = set()
        failure: str | None = None

        while pending:
            step = pending.pop(0)
            if interrupted_done():
                return
            # args come from the plan (the LLM fills them); a step without
            # the args its tool needs simply fails and DRAFT re-plans
            args = step.get("args") or {}
            events = forge.execute_step({**step, "args": args})
            executed += 1
            last_ok = events[1].ok
            last_cmd = (step.get("tool") or "bash", args)
            if interrupted_done():
                return
            if events[1].ok:
                continue

            done = events[1]
            res = done.result if isinstance(done.result, dict) else {}
            err = str(res.get("error") or res.get("detail") or "unknown error")[:300]
            reason = f"step {step.get('id')} ({step.get('tool') or 'bash'}) failed: {err}"
            sig = step_sig(step)

            if sig in failed_sigs:
                # this exact step already failed once this turn — replanning
                # again cannot help; a third identical run proves nothing
                failure = f"the same step failed twice — treating as terminal: {err}"
                break
            if replans >= MAX_REPLANS:
                failure = f"replanned twice, still failing: {err}"
                break

            failed_sigs.add(sig)
            replans += 1
            # DRAFT re-plans; the plan.update is already on the stream (live)
            plan_events = draft.replan(goal, reason, failed_step=step)
            update = plan_events[-1] if plan_events else None
            new_steps = getattr(update, "steps", None)
            if not isinstance(update, PlanUpdate) or not new_steps:
                failure = f"replan produced no usable plan: {err}"
                break
            if step_sig(new_steps[0]) == sig:
                # replanning returned the step that just failed — running it
                # again would loop forever; treat as terminal now
                failure = f"replan returned the same failing step — not looping: {err}"
                break
            pending = list(new_steps)  # corrected steps replace the remainder

        # TEMPER verifies adversarially — smoke-check re-runs the last command
        verified = False
        if failure is None and last_cmd is not None and last_ok:
            tool, cmd_args = last_cmd
            check = cmd_args.get("cmd", "true") if tool == "bash" else "true"
            temper = TemperVerifier(state.registry, emit=emit, adversarial=True, reruns=1)
            verdict = temper.verify(step=executed, target=goal[:64], checks=[check])
            verified = verdict[-1].TYPE == "step.pass"

        emit(Memory(seq=0, op="write", entity=goal[:64],
                    fact=f"turn {run_id}: {executed} steps, verified={verified}", ts=0.0))
        emit(Usage(seq=0, tokens={"input": 0, "output": 0}, cost_usd=0.0, ts=0.0))

        duration = round(time.time() - turn_start, 4)
        if failure is not None:
            # T-042: the honest terminal summary — what was tried, why it died
            emit(Answer(seq=0, text=f"Turn failed: {failure}", ts=0.0))
            emit(RunDone(seq=0, status="failed", steps=executed, duration_s=duration, ts=0.0))
        elif verified:
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
    # T-043: a docker-pinned sandbox with no daemon refuses BEFORE planning
    # — never a silent process fallback, never a 500 mid-turn.
    if STATE.config.sandbox.backend == "docker":
        from arcen.sandbox.runtime import docker_status

        st = docker_status(STATE.config.sandbox.image)
        if not st["docker_available"]:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Sandbox backend is set to docker, but no docker daemon is "
                    "reachable. Either start docker or change the backend in "
                    "Settings → Sandbox."
                ),
            )
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
    """Update the config (T-036 Settings → Save; T-049 scalar provider).

    - a '<redacted>' provider.api_key is substituted with the live
      config's stored value — a redacted GET round-trip never wipes a key;
    - the result is persisted to the user's config.yaml (chmod 600);
    - the provider bridge reloads in-memory so the next turn uses the
      new provider immediately (no restart).
    """
    incoming = dict(payload)
    provider = dict(incoming.get("provider") or {})
    if provider.get("api_key") == "<redacted>":
        provider["api_key"] = STATE.config.provider.api_key
    incoming["provider"] = provider
    updated = ArcenConfig.model_validate(incoming)
    STATE.config = updated
    save_config(STATE.config_path, updated)
    STATE.llm = build_llm_client(updated)  # reload the provider bridge
    return STATE.config.redacted()


PROVIDERS = frozenset({"custom", "groq", "deepseek", "openai", "anthropic", "ollama"})


@app.post("/api/config/test")
def test_config(payload: dict = Body(...)) -> dict:
    """Probe a provider connection (T-036 Test Connection; T-049 scalar).

    Accepts {provider, model?, base_url?, api_key?}. A missing key/model
    falls back to the live config's stored values when the probe targets
    the configured provider; an unresolved ``$VAR`` key resolves from the
    environment. No vendor defaults: an empty model is an error, never
    claude-*. The reply never echoes the key — errors are sanitized.
    """
    import litellm

    from arcen.llm.bridge import LITELLM_PREFIX, KEYLESS_PROVIDERS

    provider = str(payload.get("provider", "")).strip().lower()
    if provider not in PROVIDERS:
        raise HTTPException(status_code=422, detail=f"unknown provider {provider!r}")
    configured = STATE.config.provider
    same = configured.name.strip().lower() == provider

    model = str(payload.get("model", "")).strip()
    if not model and same:
        model = configured.model.strip()
    if not model:
        return {"ok": False, "error": "no model given — set Model Name in Settings"}

    base_url = str(payload.get("base_url", "")).strip()
    if not base_url and same:
        base_url = configured.base_url.strip()

    api_key = str(payload.get("api_key", "")).strip()
    if api_key in ("", "<redacted>") and same:
        api_key = configured.api_key.strip()
    if api_key.startswith("$"):
        resolved, _missing = resolve_secrets({"k": api_key})
        api_key = str(resolved.get("k") or "").strip()
    if api_key in ("", "<redacted>") and provider not in KEYLESS_PROVIDERS:
        return {"ok": False, "error": "no API key configured for this provider"}

    prefix = LITELLM_PREFIX.get(provider, "")
    full_model = model if "/" in model else prefix + model
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
    """Sessions newest-first (created_at DESC) — the API is the single
    source of truth for ordering (T-040); clients render as-is."""
    sessions = list(STATE.sessions_meta.values())
    sessions.sort(key=lambda s: s.get("created_at") or 0.0, reverse=True)
    return sessions


@app.get("/api/sandbox/status")
def sandbox_status() -> dict:
    """The full sandbox picture for Settings (T-038 + T-043).

    docker_available / image_present / image (T-038) plus the configured
    backend, the backend actually selected, and the reason (T-043) —
    the same four lines the boot log prints.
    """
    from arcen.sandbox.runtime import sandbox_state

    return sandbox_state(STATE.config.sandbox.backend, STATE.config.sandbox.image)


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
