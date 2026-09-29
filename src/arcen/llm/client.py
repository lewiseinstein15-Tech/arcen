"""ARCEN — LLM bridge (BACKEND-SPEC Part 2, row 14).

Pulled from LiteLLM — provider routing, retries, cost metering.
Edited: fixed per-role model mapping (planner/executor/verifier) and an
ARCEN identity block prepended to every call so each model speaks as the
correct core agent (DRAFT / FORGE / TEMPER).

Roles are fixed: planner→DRAFT, executor→FORGE, verifier→TEMPER.
Model names are passed in by the bridge (llm/bridge.py): the agent's
own ``agents.<name>.model`` or the inherited ``provider.model`` —
no vendor defaults live here (T-049/T-050). Credentials are resolved
from the environment by the credential vault — never literals.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import litellm

litellm.suppress_debug_info = True

# -- v0.1.6: the fail-fast provider error contract ---------------------------

# HTTP statuses that are NEVER retried: the request itself is wrong and a
# second identical call cannot succeed (spec B). 401 is the classic — a
# bad API key retried five times is five identical failures.
NO_RETRY_STATUSES = frozenset({400, 401, 403, 404})
# HTTP statuses worth a second (and up to ``provider.max_retries``) call:
# transient server-side / throttling failures (spec B).
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503})

# Human hints for the statuses users actually hit (spec E) — the Test
# Connection button shows these verbatim.
_STATUS_HINTS: dict[int, str] = {
    400: "bad request — check Model Name and Base URL",
    401: "unauthorized — check your API key",
    403: "forbidden — check key permissions",
    404: "not found — check Model Name and Base URL",
    429: "rate limited — check your quota or slow down",
    500: "provider server error — try again shortly",
    502: "provider gateway error — try again shortly",
    503: "provider unavailable — try again shortly",
}

_PREFIX_NOISE = re.compile(r"(?:litellm\.\w+\s*:\s*)+")


def _brief_text(exc: Exception) -> str:
    """A one-line, human-readable excerpt of the provider's complaint.

    Spec A: the response body's cause travels with the error. Preference:
    an OpenAI-shaped body message, the exception text with litellm's
    stacked class-name prefixes stripped, then a plain str(). Whitespace
    collapses; the excerpt caps at 160 chars so the stream line stays
    readable. The caller redacts secrets before displaying.
    """
    body = getattr(exc, "body", None)
    text = ""
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            text = str(err["message"])
        elif isinstance(err, str):
            text = err
        elif body.get("message"):
            text = str(body["message"])
    if not text:
        text = str(exc)
    text = _PREFIX_NOISE.sub("", text)
    text = " ".join(text.split())  # newlines + runs of spaces → one line
    return text[:160]


def classify_provider_failure(exc: Exception) -> tuple[int | None, str, str]:
    """(status, brief, kind) for a provider exception.

    kind is one of 'timeout' (the call hung and was cancelled — never
    retried, spec D), 'status' (the provider answered with an HTTP
    status), 'connection' (never reached the provider — transient), or
    'unknown' (a non-provider failure — treated as transient). Duck-typed
    on ``status_code`` and the class name so it survives litellm/openai
    version drift (litellm re-exports the timeout class under different
    names across versions — litellm.Timeout, openai.APITimeoutError).
    """
    timeout_cls = getattr(litellm, "Timeout", None) or getattr(
        litellm.exceptions, "Timeout", None
    )
    is_timeout = (
        (timeout_cls is not None and isinstance(exc, timeout_cls))
        or "APITimeoutError" in type(exc).__name__
        or (
            "timed out" in str(exc).lower()
            and getattr(exc, "status_code", None) is None
        )
    )
    if is_timeout:
        return None, _brief_text(exc), "timeout"
    status = getattr(exc, "status_code", None)
    if isinstance(status, bool):
        status = None
    if isinstance(status, int) and status > 0:
        return status, _brief_text(exc), "status"
    name = type(exc).__name__.lower()
    if "connection" in name or "conn" in name:
        return None, _brief_text(exc), "connection"
    return None, _brief_text(exc), "unknown"


def format_provider_error(
    status: int | None,
    brief: str,
    kind: str,
    timeout_s: float | None = None,
    use_hint: bool = False,
) -> str:
    """The user-facing one-liner: ``provider error: <status> <brief>``.

    Timeouts name their budget explicitly (spec D). The stream (default)
    shows the provider's OWN brief message (spec A — the recorded body
    excerpt). ``use_hint=True`` (the Test Connection probe, spec E)
    prefers the canned fix-it hint — "401 unauthorized — check your API
    key" — falling back to the brief for statuses without one.
    """
    if kind == "timeout":
        return f"provider error: timeout after {timeout_s:g}s" if timeout_s else "provider error: timeout"
    if status is not None:
        if use_hint:
            hint = _STATUS_HINTS.get(status)
            if hint:
                return f"provider error: {status} {hint}"
        if brief:
            return f"provider error: {status} {brief}"
        return f"provider error: {status}"
    return f"provider error: {brief}".rstrip()


class ProviderError(RuntimeError):
    """A provider call failed for good — the cause is on the record.

    Raised by ``Client.complete`` after the retry policy is exhausted (or
    immediately for permanent failures). ``status`` is the HTTP status
    when the provider answered, else None. ``str(exc)`` is the spec's
    wire format: ``provider error: <status> <brief message>`` — this is
    what the stream's ``run.error`` event and the Test Connection button
    display.
    """

    def __init__(self, message: str, status: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable

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


class Client:
    """The one LLM bridge. Fixed per-role model mapping over LiteLLM.

    ``models`` maps role → concrete model name and comes from the bridge
    (provider.model + agents inheritance). A role with no model is a
    configuration error — model_for raises rather than inventing one.
    """

    def __init__(
        self,
        models: dict[str, str] | None = None,
        max_retries: int = 2,
        retry_backoff_seconds: float = 1.0,
        completion_fn: Callable[..., Any] | None = None,
    ) -> None:
        # fixed per-role mapping — callers cannot pass arbitrary models per call
        self.models = dict(models or {})
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self._completion = completion_fn or litellm.completion

    def model_for(self, role: str) -> str:
        if role not in ROLE_AGENTS:
            raise ValueError(f"unknown role {role!r}; expected one of {sorted(ROLE_AGENTS)}")
        model = self.models.get(role, "").strip()
        if not model:
            raise ValueError(
                f"no model configured for role {role!r} — set Model Name in Settings"
            )
        return model

    def is_available(self) -> bool:
        """True when a usable provider credential was resolved (T-037).

        The bridge (llm/bridge.py) only constructs a Client after an api
        key resolves from config/env — or for a keyless local runtime
        (ollama). Construction therefore implies availability. Kept as a
        method so future liveness probes (e.g. pinging an ollama host)
        slot in without touching callers.
        """
        return True

    def complete(
        self,
        role: str,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        identity: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """One completion for a fixed role, identity block prepended.

        ``identity`` overrides the role's default identity block — used by
        the DIRECT conversational path so answers speak as ARCEN itself
        ("You are ARCEN. Answer concisely and directly.") instead of the
        planning persona. Meters tokens and cost from the provider
        response. Never mutates the caller's list.

        v0.1.6 retry policy (ARCEN owns retries — the bridge disables
        litellm's):
        - 400/401/403/404 → fail immediately, no retry (spec B);
        - 429/500/502/503 → up to ``max_retries`` retries with exponential
          backoff ``retry_backoff_seconds`` * 2^k → 1s, 2s, 4s (spec C);
        - timeout (default 60s, spec D) → the call is cancelled and
          reported immediately — a call that already burned its whole
          budget is not worth another one;
        - the FIRST failure's status + body excerpt is recorded and
          surfaced when the last attempt dies (spec A).
        Every exhaustion raises ``ProviderError`` in the wire format
        ``provider error: <status> <brief message>``.
        """
        model = self.model_for(role)
        prepped = [
            {"role": "system", "content": identity if identity is not None else identity_block(role)},
            *messages,
        ]
        kwargs.setdefault("timeout", 60)  # spec D: the per-call budget
        first: tuple[int | None, str, str] | None = None
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
                status, brief, kind = classify_provider_failure(exc)
                if first is None:
                    first = (status, brief, kind)  # spec A: first failure on record
                if kind == "timeout":
                    # spec D: cancel and report — never re-hang the turn
                    raise ProviderError(
                        format_provider_error(status, brief, kind, kwargs.get("timeout")),
                        status=None,
                    ) from exc
                if status is not None and status in NO_RETRY_STATUSES:
                    raise ProviderError(
                        format_provider_error(status, brief, kind), status=status
                    ) from exc
                transient = status is None or status in RETRYABLE_STATUSES
                if not transient or attempt >= self.max_retries:
                    break
                time.sleep(self.retry_backoff_seconds * (2**attempt))  # 1s, 2s, 4s
        assert last_exc is not None and first is not None
        status, brief, kind = first
        raise ProviderError(
            format_provider_error(status, brief, kind, kwargs.get("timeout"))
            + f" (after {self.max_retries + 1} attempts)",
            status=status,
        ) from last_exc
