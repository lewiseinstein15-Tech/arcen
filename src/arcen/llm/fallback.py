"""Provider fallbacks — one turn, several providers, no single point of death.

Phase 8 of the GLM-5.4 adaptation: the architecture must not be welded to
one vendor. ARCEN already lets each agent run on its own model
(``agents.<name>.model``); this adds the missing half — a *second* provider
to call when the first one is dead.

Fallback is deliberately narrow:

- it fires only on :class:`ProviderError` (a real provider failure), never
  on a programming error, so bugs are not silently retried elsewhere;
- it is ordered and reported: the reason the primary failed travels with
  the response so the stream can say which provider actually answered;
- the first success wins and later providers are not called.

It does not merge answers, vote, or synthesize — that would be a different
architecture with different failure modes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from arcen.llm.client import ProviderError


class FallbackClient:
    """A role-compatible proxy over an ordered list of clients."""

    def __init__(
        self,
        clients: list[Any],
        *,
        on_fallback: Callable[[int, ProviderError], None] | None = None,
    ) -> None:
        if not clients:
            raise ValueError("FallbackClient needs at least one client")
        self.clients = list(clients)
        self.on_fallback = on_fallback
        self.last_used: int = 0

    @property
    def prompts(self) -> Any:
        return getattr(self.clients[0], "prompts", None)

    @property
    def models(self) -> dict[str, str]:
        return getattr(self.clients[0], "models", {})

    def model_for(self, role: str) -> str:
        """The model that actually serves ``role``.

        Reflects the provider that last answered, so a verifier's
        independence check compares against the model that really ran
        rather than the one that was configured first.
        """
        return self.clients[self.last_used].model_for(role)

    def is_available(self) -> bool:
        return any(bool(getattr(c, "is_available", lambda: True)()) for c in self.clients)

    def complete(self, role: str, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        failures: list[str] = []
        for index, client in enumerate(self.clients):
            try:
                response = client.complete(role, messages, **kwargs)
            except ProviderError as exc:
                failures.append(f"provider {index + 1}: {exc}")
                if self.on_fallback is not None:
                    self.on_fallback(index, exc)
                continue
            self.last_used = index
            return response
        raise ProviderError("; ".join(failures) or "all providers failed")
