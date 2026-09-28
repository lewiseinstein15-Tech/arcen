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

Intent classification (T-031): the old hardcoded greeting list sent
everything else — "2+2", "what is your name", "explain closures" — into
the bash planner, which failed them (BUG 2's bigger sibling). DRAFT now
classifies EVERY goal with the LLM:

- DIRECT   — answerable by the model alone, no tools (greetings, math,
             facts, questions about itself, explanations) → no plan, the
             LLM answers under the ARCEN identity;
- RESEARCH — needs web search or a URL read → plan with web tools;
- CODE     — needs file/bash/python tools → the normal plan pipeline;
- UNKNOWN  — classifier unparseable/unavailable → CODE (the old default).

With ``llm=None`` a deterministic heuristic classifier keeps offline mode
honest: greetings still get the warm reply, real tasks still get plans.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable

from arcen.llm.client import Client
from arcen.stream.events import Answer, Event, Plan, PlanUpdate, Think, to_line

SYSTEM_HINT = """Return ONLY a JSON array of 1-6 steps for this goal, shaped:
[{"title": "imperative step", "tool": "bash|file.read|file.edit|file.write|search.text|..."}]
No prose, no markdown fences."""

RESEARCH_HINT = """Return ONLY a JSON array of 1-4 steps to RESEARCH this goal, shaped:
[{"title": "imperative step", "tool": "search.text|http.get|http.post|file.read|file.write"}]
Prefer search.text for queries and http.get for specific URLs. No prose, no markdown fences."""

CLASSIFY_HINT = """Classify this user message into one of:
DIRECT    — answerable by you directly, no tools needed
            (greetings, math, definitions, facts, opinions,
            questions about yourself)
RESEARCH  — needs web search or reading a URL
CODE      — needs to read/write files, run commands, execute code
Return ONLY the word: DIRECT, RESEARCH, or CODE."""

# the DIRECT answer persona (T-031): the model speaks as ARCEN itself
DIRECT_IDENTITY = "You are ARCEN. Answer concisely and directly."

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

# web tools available to RESEARCH plans (offline heuristic uses these)
RESEARCH_TOOLS = ("search.text", "http.get")

# Intent is one of the four frozen values (UNKNOWN included).
DIRECT = "DIRECT"
RESEARCH = "RESEARCH"
CODE = "CODE"
UNKNOWN = "UNKNOWN"
INTENTS = frozenset({DIRECT, RESEARCH, CODE, UNKNOWN})

# -- the offline heuristic classifier (llm=None fallback) --------------------

# single pleasantries — the whole (punctuation-stripped) message
_CONVERSATIONAL_WORDS = frozenset(
    {"hello", "hi", "hey", "yo", "thanks", "thank", "bye", "goodbye", "ok", "okay", "sup", "greetings"}
)

# short social / self questions — matched as full (punctuation-stripped) messages
_CONVERSATIONAL_PHRASES = frozenset(
    {
        "how are you",
        "who are you",
        "who built you",
        "who made you",
        "what is your name",
        "whats your name",
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

# research-shaped verbs/nouns — the offline RESEARCH trigger
_RESEARCH_WORDS = frozenset(
    {"search", "google", "browse", "weather", "news", "look", "lookup", "find", "latest", "today's"}
)

# question shapes a model can answer with no tools (offline DIRECT trigger)
_DIRECT_Q = re.compile(
    r"^(what|who|why|how|when|where|which|explain|define|tell me|do you|are you|can you)\b.{0,120}$"
)
# arithmetic shapes — "2+2", "what is 2+2?", "17 * 23", "sqrt(144)"
_ARITH = re.compile(r"^[\d\s+\-*/^().%]+$|^(what\s+is\s+)?[\d\s+\-*/^().%]+[?!.]*$")
_ARITH_CORE = re.compile(r"\d")

# the offline warm reply (no provider configured) — 1-2 sentences, on-brand
CONVERSATIONAL_REPLY = (
    "Hello! I'm ARCEN — DRAFT plans, FORGE executes, TEMPER verifies, and every "
    "step lands live on the stream. Give me a coding task and I'll get to work."
)


def classify_intent(text: str, llm: Client | None = None) -> str:
    """Classify a user message → DIRECT | RESEARCH | CODE | UNKNOWN.

    LLM-first (the whole point of T-031: a word list cannot read intent).
    The message + CLASSIFY_HINT go to the planner role; the reply is
    matched against the three intent words — anything unparseable is
    UNKNOWN. With no LLM (or a provider error) a deterministic heuristic
    keeps offline mode usable: greetings and self-questions DIRECT,
    search/weather phrasing RESEARCH, everything else CODE.
    """
    stripped = text.strip()
    if not stripped:
        return DIRECT  # an empty ping is conversational, never a bash plan

    if llm is not None:
        try:
            resp = llm.complete(
                "planner",
                [{"role": "user", "content": f"{stripped}\n\n{CLASSIFY_HINT}"}],
                temperature=0.0,
            )
            word = _parse_intent_word(resp.text)
            if word is not None:
                return word
            return UNKNOWN  # provider answered, but not with an intent
        except Exception:  # noqa: BLE001 — provider down → heuristic
            pass

    return _classify_heuristic(stripped)


def _parse_intent_word(reply: str) -> str | None:
    """Pull DIRECT/RESEARCH/CODE out of a (possibly noisy) LLM reply."""
    upper = reply.upper()
    for word in (DIRECT, RESEARCH, CODE):
        if word in upper:
            return word
    return None


def _classify_heuristic(stripped: str) -> str:
    """Deterministic fallback: DIRECT / RESEARCH / CODE without an LLM."""
    lowered = stripped.lower().rstrip("!.?,;: ")
    if lowered in _CONVERSATIONAL_WORDS or lowered in _CONVERSATIONAL_PHRASES:
        return DIRECT
    words = lowered.split()
    # "hi there" / "hey arcen" / "thanks again" — greeting + ≤2 trailing words
    if words and words[0] in _CONVERSATIONAL_WORDS and len(words) <= 3:
        return DIRECT
    # questions about itself / pure arithmetic → the model knows these
    if _ARITH_CORE.search(lowered) and _ARITH.match(lowered.replace("what is", "").strip()):
        return DIRECT
    if lowered.startswith(("what is your", "who built you", "who made you", "what are you")):
        return DIRECT
    # research-shaped asks
    if any(w in _RESEARCH_WORDS for w in words):
        return RESEARCH
    # short general questions are answerable directly by a real model
    if len(words) <= 6 and _DIRECT_Q.match(lowered):
        return DIRECT
    return CODE


def is_conversational(text: str) -> bool:
    """Backward-compat shim (BUG 2 era): True when the intent is DIRECT.

    Superseded by classify_intent — kept so older callers keep working.
    """
    return classify_intent(text) == DIRECT


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
        """Goal in → intent out.

        DIRECT  → ``think`` + ``answer`` (no plan, no tools — the ARCEN
                  identity answers; T-031).
        RESEARCH/CODE → ``think`` + ``plan`` (web tools / file+bash tools).
        UNKNOWN → treated as CODE (the pre-T-031 default).
        """
        intent = classify_intent(goal, self.llm)
        if intent == DIRECT:
            return self._direct_reply(goal)
        if intent == RESEARCH:
            return self._research_turn(goal, depth)
        return self._code_turn(goal, depth)

    # -- DIRECT: the LLM answers, no plan, no tools ------------------------
    def _direct_reply(self, goal: str) -> list[Event]:
        events: list[Event] = [
            Think(seq=0, agent="DRAFT", text="direct question — answering without tools.", ts=0.0)
        ]
        reply = CONVERSATIONAL_REPLY if _is_greeting(goal) else (
            "No provider configured — I can't answer from a model right now, "
            "but I can still run coding tasks offline."
        )
        if self.llm is not None:
            try:
                resp = self.llm.complete(
                    "planner",
                    [{"role": "user", "content": goal}],
                    identity=DIRECT_IDENTITY,
                )
                reply = resp.text.strip() or reply
            except Exception:  # noqa: BLE001 — provider down → offline reply
                pass
        events.append(Answer(seq=0, text=reply, ts=0.0))
        return self._emit_all(events)

    # -- RESEARCH: plan with web tools --------------------------------------
    def _research_turn(self, goal: str, depth: int) -> list[Event]:
        think_text, steps = self._decompose(goal, depth, hint=RESEARCH_HINT)
        if steps and any(s.get("tool") in RESEARCH_TOOLS for s in steps):
            pass  # LLM gave web-shaped steps — use them
        else:
            steps = self._research_heuristic(goal)
        events: list[Event] = [
            Think(seq=0, agent="DRAFT", text=think_text, ts=0.0),
            Plan(seq=0, agent="DRAFT", steps=steps, ts=0.0),
        ]
        return self._emit_all(events)

    def _research_heuristic(self, goal: str) -> list[dict]:
        """Deterministic offline research: search → fetch → summarize."""
        return [
            {"id": 1, "title": f"search the web for: {goal}", "tool": "search.text"},
            {"id": 2, "title": "fetch the most relevant result", "tool": "http.get"},
            {"id": 3, "title": "summarize the findings for the user", "tool": None},
        ]

    # -- CODE: the normal pipeline ------------------------------------------
    def _code_turn(self, goal: str, depth: int) -> list[Event]:
        think_text, steps = self._decompose(goal, depth)
        events: list[Event] = [
            Think(seq=0, agent="DRAFT", text=think_text, ts=0.0),
            Plan(seq=0, agent="DRAFT", steps=steps, ts=0.0),
        ]
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
        hint: str = SYSTEM_HINT,
    ) -> tuple[str, list[dict]]:
        if self.llm is not None:
            try:
                return self._decompose_llm(goal, depth, failed_step, hint)
            except Exception:
                pass  # provider down → degrade, never block the turn
        return self._decompose_heuristic(goal, failed_step)

    def _decompose_llm(
        self,
        goal: str,
        depth: int,
        failed_step: dict | None,
        hint: str,
    ) -> tuple[str, list[dict]]:
        assert self.llm is not None
        user = f"Goal: {goal}"
        if failed_step:
            user += f"\nThe step {json.dumps(failed_step)} failed. Plan around it."
        resp = self.llm.complete(
            "planner",
            [{"role": "user", "content": user + "\n" + hint}],
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
        think = f"Goal: {goal}. Plan has {len(steps)} step(s)."
        return think, steps

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


def _is_greeting(goal: str) -> bool:
    """True for plain pleasantries — they get the warm offline reply."""
    lowered = goal.strip().lower().rstrip("!.?,;: ")
    words = lowered.split()
    return lowered in _CONVERSATIONAL_WORDS or (
        bool(words) and words[0] in _CONVERSATIONAL_WORDS and len(words) <= 3
    )


def main(argv: list[str]) -> int:
    """`python -m arcen.agents.draft "goal"` — plan offline, print NDJSON."""
    goal = argv[1] if len(argv) > 1 else "run the test suite and fix failures"
    planner = DraftPlanner(llm=None)
    for event in planner.open_turn(goal):
        print(to_line(event))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
