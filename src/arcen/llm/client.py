"""ARCEN — LLM bridge (BACKEND-SPEC Part 2, row 14).

Pulled from LiteLLM — provider routing, retries, cost metering.
Edited: fixed per-role model mapping (planner/executor/verifier) and an
ARCEN identity block prepended to every call so each model speaks as the
correct core agent (DRAFT / FORGE / TEMPER).

Roles are fixed: planner→DRAFT, executor→FORGE, verifier→TEMPER.
Model names come from config ``provider.models``; credentials are
resolved from the environment by the credential vault — never literals.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

import litellm

litellm.suppress_debug_info = True

# role → core agent. Fixed by spec; a fourth role is a spec violation.
ROLE_AGENTS: dict[str, str] = {
    "planner": "DRAFT",
    "executor": "FORGE",
    "verifier": "TEMPER",
}

IDENTITY = """You are {agent}, one of three core agents inside ARCEN (Agentic reasoning + Code + Engineer).

ARCEN is an agentic engineer that plans, builds, and verifies — with every action narrated on a live NDJSON stream. It does not invent: it pulls from the best open-source agent projects, edits only what is needed, wires it, and tests it.

Your job as {agent}: {job}

Narrate your reasoning — it streams to the user verbatim. Be precise, be brief, and never claim work you have not done."""

ROLE_JOBS: dict[str, str] = {
    "planner": (
        "you open every turn. Break the goal into concrete steps, decide which "
        "tools fit each step, spawn sub-agents for parallel work, and re-plan "
        "when a step fails. You never execute tools yourself."
    ),
    "executor": (
        "you execute exactly one tool step at a time and return the raw "
        "observation. No planning ahead, no batching, no skipping."
    ),
    "verifier": (
        "you verify adversarially — try to break the work. Run the checks, "
        "probe edge cases, and report a binary pass/fail with reasons."
    ),
}


def identity_block(role: str) -> str:
    """The system identity block for a role — present in every call."""
    if role not in ROLE_AGENTS:
        raise ValueError(f"unknown role {role!r}; expected one of {sorted(ROLE_AGENTS)}")
    agent = ROLE_AGENTS[role]
    return IDENTITY.format(agent=agent, job=ROLE_JOBS[role])


@dataclass
class LLMResponse:
    """A completion plus its metering. Mirrors the ``usage`` event shape."""

    text: str
    model: str
    tokens: dict[str, int] = field(default_factory=lambda: {"input": 0, "output": 0})
    cost_usd: float = 0.0
    duration_s: float = 0.0


DEFAULT_MODELS: dict[str, str] = {
    "planner": "claude-sonnet-4-5",
    "executor": "claude-sonnet-4-5",
    "verifier": "claude-haiku-4-5",
}


class Client:
    """The one LLM bridge. Fixed per-role model mapping over LiteLLM."""

    def __init__(
        self,
        models: dict[str, str] | None = None,
        max_retries: int = 2,
        completion_fn: Callable[..., Any] | None = None,
    ) -> None:
        # fixed per-role mapping — callers cannot pass arbitrary models per call
        self.models = {**DEFAULT_MODELS, **(models or {})}
        self.max_retries = max_retries
        self._completion = completion_fn or litellm.completion

    def model_for(self, role: str) -> str:
        if role not in ROLE_AGENTS:
            raise ValueError(f"unknown role {role!r}; expected one of {sorted(ROLE_AGENTS)}")
        return self.models[role]

    def complete(
        self,
        role: str,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        **kwargs: Any,
    ) -> LLMResponse:
        """One completion for a fixed role, identity block prepended.

        Retries transient failures; meters tokens and cost from the
        provider response. Never mutates the caller's message list.
        """
        model = self.model_for(role)
        prepped = [
            {"role": "system", "content": identity_block(role)},
            *messages,
        ]
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            start = time.monotonic()
            try:
                resp = self._completion(
                    model=model,
                    messages=prepped,
                    temperature=temperature,
                    **kwargs,
                )
                duration = time.monotonic() - start
                usage = getattr(resp, "usage", None)
                tokens = {
                    "input": getattr(usage, "prompt_tokens", 0) if usage else 0,
                    "output": getattr(usage, "completion_tokens", 0) if usage else 0,
                }
                cost = 0.0
                try:
                    cost = float(litellm.completion_cost(resp) or 0.0)
                except Exception:
                    cost = 0.0  # metering is best-effort; never blocks a turn
                text = resp.choices[0].message.content or ""
                return LLMResponse(
                    text=text,
                    model=model,
                    tokens=tokens,
                    cost_usd=cost,
                    duration_s=round(duration, 4),
                )
            except Exception as exc:  # noqa: BLE001 — LiteLLM raises many shapes
                last_exc = exc
                if attempt < self.max_retries:
                    continue
        raise RuntimeError(f"LLM bridge failed after {self.max_retries + 1} attempts: {last_exc}") from last_exc
