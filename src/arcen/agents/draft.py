"""ARCEN — DRAFT, the planner (BACKEND-SPEC Part 1 / Part 2 row 1).

Pulled from Aider (aider/coders/architect_coder.py) — the architect/editor
split and the plan-then-reflect decomposition loop.

Edited per the Pull Map:
- prompts reduced to the 3-agent shape (DRAFT plans, never executes);
- emits ``think`` / ``plan`` / ``plan.update`` on the frozen event schema;
- spawn hooks left to the sub-agent spawner (T-011) — DRAFT only decides.

DRAFT opens every turn: goal in → narrated reasoning + a step list out.
Every step is {id, title, tool}. When TEMPER fails the work, ``replan``
emits ``plan.update`` with the reason and the corrected steps.

Offline mode: with ``llm=None`` (or when the provider errors) DRAFT falls
back to a deterministic inspect → act → verify decomposition, so planning
never blocks on a provider.

Conversational short-circuit: greetings and pleasantries ("hello",
"hi there", "how are you") get a warm 1-2 sentence reply — never a
plan, never a tool call. Planning a bash run for "hello" (exit 127)
was the BUG 2 failure this guards against.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable

from arcen.llm.client import Client
from arcen.stream.events import Answer, Event, Plan, PlanUpdate, Think, to_line

SYSTEM_HINT = """Return ONLY a JSON array of 1-6 steps for this goal, shaped:
[{"title": "imperative step", "tool": "bash|file.read|file.edit|file.write|search.text|..."}]
No prose, no markdown fences."""

KNOWN_TOOLS = {
    "bash",
    "file.read",
    "file.write",
    "file.edit",
    "file.append",
    "file.delete",
    "file.copy",
    "file.move",
    "file.list",
    "file.glob",
    "file.mkdir",
    "search.text",
    "search.files",
    "search.symbols",
    "search.replace",
    "code.run",
    "code.eval_expr",
    "code.format",
    "code.outline",
    "code.diff",
    "http.get",
    "http.post",
    "http.head",
}

# -- the conversational short-circuit (BUG 2 fix) ----------------------------

# single pleasantries — the whole (punctuation-stripped) message
_CONVERSATIONAL_WORDS = frozenset(
    {"hello", "hi", "hey", "yo", "thanks", "thank", "bye", "goodbye", "ok", "okay", "sup", "greetings"}
)

# short social questions — matched as full (punctuation-stripped) messages
_CONVERSATIONAL_PHRASES = frozenset(
    {
        "how are you",
        "who are you",
        "what's up",
        "whats up",
        "what is up",
        "good morning",
        "good afternoon",
        "good evening",
        "good night",
        "nice to meet you",
        "are you there",
        "can you hear me",
        "long time no see",
        "what can you do",
    }
)

# the offline warm reply (no provider configured) — 1-2 sentences, on-brand
CONVERSATIONAL_REPLY = (
    "Hello! I'm ARCEN — DRAFT plans, FORGE executes, TEMPER verifies, and every "
    "step lands live on the stream. Give me a coding task and I'll get to work."
)


def is_conversational(text: str) -> bool:
    """True for greetings/pleasantries that deserve a reply, not a plan.

    Matches single words ("hello", "hi!", "yo."), greetings with small
    trailing words ("hi there", "hey arcen"), and short social questions
    ("how are you", "who are you", "what's up"). Real tasks — even short
    ones like "what is 2+2" or "build me a calculator" — are NOT
    conversational and go through the normal planning pipeline.
    """
    stripped = text.strip().lower().rstrip("!.?,;: ")
    if not stripped:
        return False
    if stripped in _CONVERSATIONAL_WORDS or stripped in _CONVERSATIONAL_PHRASES:
        return True
    words = stripped.split()
    # "hi there" / "hey arcen" / "thanks again" — a greeting plus at most
    # two trailing words. "ok now build the app" (5 words) stays a task.
    return bool(words) and words[0] in _CONVERSATIONAL_WORDS and len(words) <= 3


class DraftPlanner:
    """The planner agent. Opens every turn; re-plans on failure."""

    def __init__(
        self,
        llm: Client | None = None,
        emit: Callable[[Event], None] | None = None,
        max_steps: int = 40,
    ) -> None:
        self.llm = llm
        self.emit = emit
        self.max_steps = max_steps

    # -- event plumbing ----------------------------------------------------
    def _emit_all(self, events: list[Event]) -> list[Event]:
        for e in events:
            e.seq = 0  # stamped by the runtime emitter; drafts stay schema-valid
            if self.emit is not None:
                self.emit(e)
        return events

    # -- the Aider architect loop, reduced ---------------------------------
    def open_turn(self, goal: str, depth: int = 0) -> list[Event]:
        """Goal in → ``think`` + ``plan`` events out — or ``think`` + ``answer``
        for conversational input (no plan, no tools; BUG 2 fix)."""
        if is_conversational(goal):
            return self._conversational(goal)
        think_text, steps = self._decompose(goal, depth)
        events: list[Event] = [
            Think(seq=0, agent="DRAFT", text=think_text, ts=0.0),
            Plan(seq=0, agent="DRAFT", steps=steps, ts=0.0),
        ]
        return self._emit_all(events)

    def _conversational(self, goal: str) -> list[Event]:
        """Greeting in → warm 1-2 sentence reply out. NEVER a plan."""
        events: list[Event] = [
            Think(seq=0, agent="DRAFT", text="the user is greeting me. responding directly.", ts=0.0)
        ]
        reply = CONVERSATIONAL_REPLY
        if self.llm is not None:
            try:
                resp = self.llm.complete("planner", [{"role": "user", "content": goal}])
                reply = resp.text.strip() or reply
            except Exception:  # noqa: BLE001 — provider down → the warm offline reply
                pass
        events.append(Answer(seq=0, text=reply, ts=0.0))
        return self._emit_all(events)

    def replan(self, goal: str, reason: str, failed_step: dict | None = None) -> list[Event]:
        """A step failed → ``think`` + ``plan.update`` with corrected steps."""
        _, steps = self._decompose(goal, 0, failed_step=failed_step)
        events: list[Event] = [
            Think(seq=0, agent="DRAFT", text=f"Re-planning: {reason}", ts=0.0),
            PlanUpdate(seq=0, agent="DRAFT", reason=reason, steps=steps, ts=0.0),
        ]
        return self._emit_all(events)

    # -- decomposition: LLM first, deterministic fallback -------------------
    def _decompose(
        self,
        goal: str,
        depth: int,
        failed_step: dict | None = None,
    ) -> tuple[str, list[dict]]:
        if self.llm is not None:
            try:
                return self._decompose_llm(goal, depth, failed_step)
            except Exception:
                pass  # provider down → degrade, never block the turn
        return self._decompose_heuristic(goal, failed_step)

    def _decompose_llm(
        self,
        goal: str,
        depth: int,
        failed_step: dict | None,
    ) -> tuple[str, list[dict]]:
        assert self.llm is not None
        user = f"Goal: {goal}"
        if failed_step:
            user += f"\nThe step {json.dumps(failed_step)} failed. Plan around it."
        resp = self.llm.complete(
            "planner",
            [{"role": "user", "content": user + "\n" + SYSTEM_HINT}],
        )
        parsed = json.loads(resp.text)
        if not isinstance(parsed, list):
            raise ValueError("plan is not a JSON array")
        steps: list[dict] = []
        for i, raw in enumerate(parsed[: self.max_steps], start=1):
            tool = raw.get("tool")
            steps.append(
                {
                    "id": i,
                    "title": str(raw.get("title", goal))[:200],
                    "tool": tool if tool in KNOWN_TOOLS else None,
                }
            )
        think = resp.text if len(resp.text) < 400 else resp.text[:400] + "…"
        return f"Goal: {goal}. Plan has {len(steps)} step(s).", steps

    def _decompose_heuristic(
        self,
        goal: str,
        failed_step: dict | None,
    ) -> tuple[str, list[dict]]:
        """Deterministic inspect → act → verify decomposition."""
        think = (
            f"Goal: {goal}. Read the relevant context first, act on it, then verify. "
            "This is the deterministic offline plan (no provider configured)."
        )
        steps = [
            {"id": 1, "title": f"survey the working directory", "tool": "file.list"},
            {"id": 2, "title": goal, "tool": "bash"},
            {"id": 3, "title": "verify the result", "tool": "bash"},
        ]
        if failed_step is not None:
            # the failing step is replaced, not retried blind — Aider's reflect()
            failed_id = failed_step.get("id")
            for i, s in enumerate(steps, start=1):
                s["id"] = i
            steps.insert(0, {"id": 0, "title": f"diagnose why step {failed_id} failed", "tool": None})
            steps = steps[: self.max_steps]
            for i, s in enumerate(steps, start=1):
                s["id"] = i
        return think, steps


def main(argv: list[str]) -> int:
    """`python -m arcen.agents.draft "goal"` — plan offline, print NDJSON."""
    goal = argv[1] if len(argv) > 1 else "run the test suite and fix failures"
    planner = DraftPlanner(llm=None)
    for event in planner.open_turn(goal):
        print(to_line(event))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
