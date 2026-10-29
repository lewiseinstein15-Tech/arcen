"""Budgeted model bridge for verified probe prompts, without probe execution.

This interface can contact a real provider if explicitly called. It never
launches tools or runs a campaign; callers must review data before sending it.
"""

from __future__ import annotations

import math
import threading
from dataclasses import fields, replace

from pydantic import ValidationError

from arcen.config import ArcenConfig, resolve_secrets
from arcen.llm.bridge import build_llm_client
from arcen.llm.client import LLMResponse, ProviderError, identity_block
from arcen.plugins.redact_secrets import redact_text

from .budget import BudgetExhausted, SharedBudget
from .probe import ProbePlan, prepare_probe
from .resolver import HarnessError
from .store import HarnessStore

MAX_CALLS = 8
MAX_INPUT_BYTES = 128 * 1024
MAX_OUTPUT_BYTES = 64 * 1024
MAX_OUTPUT_TOKENS = 1024
CALL_TIMEOUT = 30


class ProbeModelError(ProviderError):
    """A bounded probe-model call is invalid, unavailable or failed."""


def _scrub(text: str, secret: str) -> str:
    safe = redact_text(text)
    if secret:
        safe = safe.replace(secret, "[REDACTED]")
    return safe


def _review_input(text: str, secret: str) -> int:
    if type(text) is not str:
        raise ProbeModelError("probe model input must be text")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeError:
        raise ProbeModelError("probe model input must be UTF-8") from None
    if size > MAX_INPUT_BYTES:
        raise ProbeModelError("probe model input exceeds limit")
    if _scrub(text, secret) != text:
        raise ProbeModelError("probe model input contains a detected secret")
    return size


class BoundProbeModel:
    """A fixed model and immutable prompt snapshot with a hard call-count cap."""

    def __init__(
        self,
        plan: ProbePlan,
        inner,
        secret: str,
        max_calls: int,
        budget: SharedBudget | None = None,
    ):
        self._plan = plan
        self._inner = inner
        self._secret = secret
        self._remaining = max_calls
        self._budget = budget
        self._lock = threading.Lock()

    @property
    def budget(self) -> SharedBudget | None:
        return self._budget

    @property
    def plan(self) -> ProbePlan:
        return self._plan

    @property
    def prompts(self):
        return self._plan.prompts

    def is_available(self) -> bool:
        return True

    @property
    def remaining_calls(self) -> int:
        with self._lock:
            return self._remaining

    def complete(
        self,
        role: str,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        identity: str | None = None,
        **kwargs,
    ) -> LLMResponse:
        """Call only the pinned provider with reviewed, bounded messages."""
        if role not in ("planner", "executor", "verifier") or kwargs:
            raise ProbeModelError("invalid probe model role or parameters")
        if (
            type(temperature) not in (int, float)
            or not math.isfinite(temperature)
            or not 0 <= temperature <= 2
        ):
            raise ProbeModelError("invalid probe model temperature")
        if identity is not None and identity != self.prompts.direct:
            raise ProbeModelError("probe identity override is not permitted")
        if type(messages) is not list or not 1 <= len(messages) <= 64:
            raise ProbeModelError("invalid probe model messages")
        size = 0
        checked_messages = []
        for message in messages:
            if (
                type(message) is not dict
                or set(message) != {"role", "content"}
                or message["role"] not in ("user", "assistant")
            ):
                raise ProbeModelError("invalid probe model message")
            content = message["content"]
            size += _review_input(content, self._secret)
            checked_messages.append({"role": message["role"], "content": content})
        system = identity if identity is not None else identity_block(role, prompts=self.prompts)
        size += _review_input(system, self._secret)
        if size > MAX_INPUT_BYTES:
            raise ProbeModelError("probe model input exceeds limit")
        with self._lock:
            if not self._remaining:
                raise ProbeModelError("probe model call budget exhausted")
            if self._budget is not None:
                try:
                    self._budget.reserve_model_call()
                except BudgetExhausted:
                    raise ProbeModelError("shared probe budget exhausted") from None
            self._remaining -= 1
        try:
            result = self._inner.complete(
                role,
                checked_messages,
                temperature=temperature,
                identity=identity,
                timeout=CALL_TIMEOUT,
                max_tokens=MAX_OUTPUT_TOKENS,
            )
            if type(result.text) is not str or not result.text.strip():
                raise ProbeModelError("probe model returned no output")
            if len(result.text.encode("utf-8")) > MAX_OUTPUT_BYTES:
                raise ProbeModelError("probe model output exceeds limit")
            return replace(
                result,
                text=_scrub(result.text, self._secret),
                model=_scrub(result.model, self._secret),
            )
        except ProbeModelError:
            raise
        except Exception:  # noqa: BLE001 — do not expose provider exception text
            # Provider exception messages and chained tracebacks can contain keys.
            raise ProbeModelError("probe model call failed") from None


def bind_probe_model(
    store: HarnessStore,
    baseline_id: str,
    candidate_id: str,
    task: str,
    config: ArcenConfig,
    *,
    max_calls: int = 4,
    budget: SharedBudget | None = None,
) -> BoundProbeModel:
    """Bind freshly verified candidate prompts to a configured fixed model.

    This function makes no provider request. Subsequent explicit `complete`
    calls may transmit reviewed data to that provider and incur cost. No model
    output, budget, pin or filename check establishes safety or improvement.
    """
    if budget is not None and type(budget) is not SharedBudget:
        raise HarnessError("invalid shared budget")
    if type(max_calls) is not int or not 1 <= max_calls <= MAX_CALLS:
        raise HarnessError("probe model call budget must be between 1 and 8")
    # Resolve once into a private config copy; a caller mutating config/env
    # afterwards cannot swap the provider or evade known-secret filtering.
    if type(config) is not ArcenConfig:
        raise HarnessError("invalid probe provider configuration")
    try:
        cfg = ArcenConfig.model_validate(config.model_dump())
    except ValidationError:
        raise HarnessError("invalid probe provider configuration") from None
    resolved, missing = resolve_secrets(
        {"api_key": cfg.provider.api_key, "base_url": cfg.provider.base_url}
    )
    if missing:
        raise HarnessError("probe provider configuration has unresolved environment references")
    secret = str(resolved.get("api_key") or "").strip()
    if secret.startswith("$") or (secret and len(secret) < 4):
        raise HarnessError("probe provider credential missing or too short to filter")
    cfg.provider.api_key = secret
    cfg.provider.base_url = str(resolved.get("base_url") or "").strip()
    cfg.provider.max_retries = 0
    plan = prepare_probe(store, baseline_id, candidate_id, task, cfg)
    for field in fields(plan.prompts):
        _review_input(getattr(plan.prompts, field.name), secret)
    _review_input(plan.task, secret)
    _review_input(cfg.provider.model, secret)
    inner = build_llm_client(cfg, prompts=plan.prompts)
    if inner is None:
        raise HarnessError("probe provider is not configured or credential is unavailable")
    return BoundProbeModel(plan, inner, secret, max_calls, budget)
