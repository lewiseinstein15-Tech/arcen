"""Frozen wire events → narration cards, chrome and rail state.

No transport lives here. The caller delivers already decoded events in wire
order; reconnect/gap handling is TUI-11. Replayed sequence numbers at or
below the last accepted sequence are ignored, preventing duplicate cards.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from typing import Any

from arcen.tui.cards import CardRegistry, spine_break
from arcen.tui.cards.plan import PlanStep
from arcen.tui.cards.verify import Check
from arcen.tui.state import CardEntry, ViewState

log = logging.getLogger(__name__)


class EventAdapter:
    """Apply ordered event dictionaries to shared TUI views.

    ``narration`` supports ``push`` and ``replace_at``; ``rail`` supports
    ``apply_state``. Header/footer are optional to keep fixture replay pure.
    """

    def __init__(self, narration, rail, header=None, footer=None, *, registry=None):
        self.narration, self.rail = narration, rail
        self.header, self.footer = header, footer
        self.registry = registry or CardRegistry()
        self.state = ViewState()
        self.handlers: dict[str, Callable[[Mapping[str, Any]], None]] = {
            "run.start": self._run_start, "think": self._think,
            "plan": self._plan, "plan.update": self._plan_update,
            "spawn": self._spawn, "spawn.done": self._spawn_done,
            "command": self._command, "command.done": self._command_done,
            "file.diff": self._diff, "verify.start": self._verify_start,
            "step.pass": self._step_pass, "step.fail": self._step_fail,
            "answer": self._answer, "memory": self._memory,
            "usage": self._usage, "run.done": self._run_done,
            "run.error": self._run_error,
        }

    def register_handler(self, event_type: str, handler: Callable[[Mapping[str, Any]], None]) -> None:
        """Register an additive event handler without modifying the spine."""
        if not event_type or not callable(handler):
            raise ValueError("event type and callable handler required")
        self.handlers[event_type] = handler

    def apply(self, event: Mapping[str, Any]) -> bool:
        """Apply one ordered event; return False for duplicate or unknown types."""
        kind = event.get("type")
        seq = event.get("seq")
        if isinstance(seq, int) and not isinstance(seq, bool) and seq <= self.state.last_seq:
            return False
        handler = self.handlers.get(kind)
        if handler is None:
            log.debug("ignoring unknown event type %r", kind)
            # Unknown additive events still consume sequence positions.
            if isinstance(seq, int) and not isinstance(seq, bool):
                self.state.last_seq = seq
            return False
        handler(event)
        if isinstance(seq, int) and not isinstance(seq, bool):
            self.state.last_seq = seq
        return True

    def _append(self, kind: str, value, model=None) -> CardEntry:
        if self.state.cards and self.state.cards[-1].kind != "run" and kind != "memory":
            self.narration.push(spine_break())
        entry = CardEntry(kind, len(self.narration.items), model)
        self.narration.push(value)
        self.state.cards.append(entry)
        return entry

    def _refresh(self, entry: CardEntry) -> None:
        self.narration.replace_at(entry.index, entry.model.render())

    def _sync_rail(self) -> None:
        s = self.state
        self.rail.apply_state({"steps_total": s.steps_total, "steps_done": s.steps_done,
            "phase": s.phase, "tokens": s.tokens, "cost_usd": s.cost_usd,
            "tools": list(s.tools), "replanning": s.replanning})

    def _phase(self, phase: str) -> None:
        self.state.phase = phase
        if self.header is not None:
            self.header.set_phase(phase)
        self._sync_rail()

    def _run_start(self, e):
        # Keep prior turns on the spine and the session's sequence watermark.
        prior_cards, last_seq = self.state.cards, self.state.last_seq
        self.state = ViewState(run_id=str(e.get("run_id", "")), status="running",
                               cards=prior_cards, last_seq=last_seq)
        if self.footer is not None:
            self.footer.set_live(True)
        self._phase("DRAFT")
        self._append("run", self.registry.create("run", self.state.run_id))
        self._append("goal", self.registry.create("goal", str(e.get("goal", ""))))

    def _think(self, e):
        agent = str(e.get("agent", "DRAFT")).lower()
        self._append("thought", self.registry.create("thought", str(e.get("text", "")),
                     label=f"{agent} · thinking"))

    @staticmethod
    def _steps(e):
        rows = e.get("steps") or []
        return [PlanStep(str(step.get("id", index + 1)), str(step.get("title", "")),
                         str(step.get("tool") or ""),
                         step.get("status", "pending") if step.get("status") in
                         ("pending", "active", "done", "fail") else "pending")
                for index, step in enumerate(rows) if isinstance(step, dict)]

    def _plan(self, e):
        model = self.registry.create("plan", self._steps(e))
        self.state.plan = self._append("plan", model.render(), model)
        self.state.steps_total, self.state.steps_done = len(model.steps), 0
        self._sync_rail()

    def _plan_update(self, e):
        if self.state.plan is None:
            self._plan(e)
        else:
            model = self.state.plan.model
            model.replace_steps(self._steps(e))
            self.state.steps_total, self.state.steps_done = len(model.steps), 0
            self._refresh(self.state.plan)
        self.state.replanning = False
        self._phase("DRAFT")
        # Keep the re-plan reason in the same checklist, not a separate card.
        if self.state.plan is not None:
            self.state.plan.model.reason = str(e.get("reason") or "")
            self._refresh(self.state.plan)

    def _plan_status(self, step, status):
        entry = self.state.plan
        if entry is None:
            return
        try:
            entry.model.set_status(str(step), status)
        except KeyError:
            return
        self._refresh(entry)

    def _spawn(self, e):
        self._append("spawn", self.registry.create("spawn", str(e.get("name", "")),
            str(e.get("task", "")), str(e.get("parent", "DRAFT")), int(e.get("depth", 1))))

    def _spawn_done(self, e):
        self._append("spawn.done", self.registry.create("spawn.done", str(e.get("name", "")),
            bool(e.get("ok")), int(e.get("calls", 0)), float(e.get("duration_s", 0))))

    def _command(self, e):
        self.state.replanning = False
        args = e.get("args") if isinstance(e.get("args"), dict) else {}
        tool = str(e.get("tool") or "bash")
        cmd = str(args.get("cmd")) if args.get("cmd") is not None else json.dumps(args, ensure_ascii=False)
        model = self.registry.create("command", cmd, tool=tool)
        self.state.commands[str(e.get("step", ""))] = self._append("command", model.render(), model)
        if tool not in self.state.tools:
            self.state.tools.append(tool)
        self._plan_status(e.get("step"), "active")
        self._phase("FORGE")

    def _command_done(self, e):
        entry = self.state.commands.pop(str(e.get("step", "")), None)
        if entry is None:
            log.debug("command.done without matching command: step %s", e.get("step"))
            return
        result = e.get("result") if isinstance(e.get("result"), dict) else {}
        detail = result.get("detail") if isinstance(result.get("detail"), dict) else result
        parts = [str(detail.get(k) or "") for k in ("stdout", "stderr")]
        if not any(parts) and result.get("error"):
            parts = [str(result["error"])]
        elif not any(parts) and detail and not {"stdout", "stderr", "exit"}.intersection(detail):
            parts = [json.dumps(detail, ensure_ascii=False, default=str)]
        output = "".join(parts)
        if output:
            entry.model.append_output(output)
        exit_code = detail.get("exit")
        entry.model.finish(exit_code=exit_code if isinstance(exit_code, int) else None,
                           duration_s=float(e.get("duration_s", 0)), ok=bool(e.get("ok")))
        self._refresh(entry)
        self._plan_status(e.get("step"), "done" if e.get("ok") else "fail")
        if not e.get("ok"):
            self.state.replanning = True
            self._phase("DRAFT")

    def _diff(self, e):
        self._append("diff", self.registry.create("diff", str(e.get("path", "")), str(e.get("patch", ""))))

    def _verify_start(self, e):
        self.state.replanning = False
        target = str(e.get("target", "verification"))
        model = self.registry.create("verify", [Check("target", target, status="active")])
        self.state.verification = self._append("verify", model.render(), model)
        self._phase("TEMPER")

    def _step_pass(self, e):
        entry = self.state.verification
        if entry is not None:
            checks = e.get("checks") or []
            if checks:
                entry.model.checks = [Check(str(i), str(check), status="pass") for i, check in enumerate(checks)]
            elif entry.model.checks:
                entry.model.set_status(entry.model.checks[-1].id, "pass")
            self._refresh(entry)
        step = e.get("step")
        if isinstance(step, int):
            self.state.steps_done = min(self.state.steps_total, max(self.state.steps_done, step))
        self._sync_rail()

    def _step_fail(self, e):
        entry = self.state.verification
        if entry is not None:
            # A verification may fail after an earlier pass update.
            entry.model.checks = [Check("failure", f"step {e.get('step', '?')}",
                                        str(e.get("reason", "")), "fail")]
            self._refresh(entry)
        self._plan_status(e.get("step"), "fail")
        self.state.replanning = True
        self._phase("DRAFT")

    def _answer(self, e):
        self._append("answer", self.registry.create("answer", str(e.get("text", ""))))

    def _memory(self, e):
        self._append("memory", self.registry.create("memory", str(e.get("op", "")),
            str(e.get("entity", "")), str(e.get("fact", ""))))

    def _usage(self, e):
        tokens = e.get("tokens") if isinstance(e.get("tokens"), dict) else {}
        self.state.tokens = int(tokens.get("input", 0)) + int(tokens.get("output", 0))
        self.state.cost_usd = float(e.get("cost_usd", 0))
        self._sync_rail()

    def _run_done(self, e):
        status = str(e.get("status", "ok"))
        self.state.status = status
        self.state.replanning = False
        if self.footer is not None:
            self.footer.set_live(False)
        self._phase("DONE" if status == "ok" else "ERROR" if status == "failed" else "IDLE")

    def _run_error(self, e):
        self._append("error", self.registry.create("error", str(e.get("code", "ERROR")),
                     str(e.get("message", ""))))
        self.state.status = "failed"
        self.state.replanning = False
        if self.footer is not None:
            self.footer.set_live(False)
        self._phase("ERROR")
