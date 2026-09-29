"""ARCEN — provider bridge: config → LLM client (T-031 / T-036 / T-049).

The server used to hardcode ``DraftPlanner(llm=None)`` — every turn took
the deterministic fallback even when a provider was configured. This
module builds the real bridge from the validated config:

- gates on the four scalar provider fields (T-049): name, base_url
  (custom/ollama), api_key (unless keyless) AND model must all be set —
  a missing model means offline, never claude-* against a custom endpoint;
- resolves ``$VAR`` api-key indirection from the environment (Part 8);
- maps the configured provider onto LiteLLM model names
  (anthropic/openai bare; groq/deepseek/ollama/custom prefixed);
- returns ``None`` when no usable credential exists → offline mode,
  planning never blocks on a provider.

A missing credential degrades, it never crashes the boot (Part 8 rule 2).
"""

from __future__ import annotations

from typing import Any

from arcen.config import VAR_PATTERN, ArcenConfig, resolve_secrets

# provider → LiteLLM model prefix. anthropic/openai model names are bare;
# the rest route through their litellm provider namespace. "custom" is any
# OpenAI-compatible endpoint (litellm's openai/ client + api_base).
LITELLM_PREFIX: dict[str, str] = {
    "groq": "groq/",
    "deepseek": "deepseek/",
    "ollama": "ollama/",
    "custom": "openai/",
}

# providers that work without an api key (local runtimes only)
KEYLESS_PROVIDERS = frozenset({"ollama"})

# providers that must carry an explicit base_url (no native endpoint)
BASEURL_REQUIRED = frozenset({"custom", "ollama"})

# role → agent config slot. Fixed by spec (llm/client.py ROLE_AGENTS maps
# the same roles onto the DRAFT/FORGE/TEMPER identities).
ROLE_AGENT_NAMES: dict[str, str] = {
    "planner": "draft",
    "executor": "forge",
    "verifier": "temper",
}


def model_for(agent_name: str, config: ArcenConfig) -> str:
    """The model an agent runs on (T-050 inheritance).

    ``agents.<name>.model`` wins; null/empty inherits the top-level
    ``provider.model``. Nothing configured → ValueError: an agent must
    never silently run on a vendor default.
    """
    slot = getattr(config.agents, agent_name, None)
    agent_model = getattr(slot, "model", None)
    chosen = str(agent_model or config.provider.model or "").strip()
    if not chosen:
        raise ValueError(
            f"no model configured for agent {agent_name!r} — set Model Name in Settings"
        )
    return chosen


def provider_ready(config: ArcenConfig) -> tuple[bool, str]:
    """The has_provider gate (T-049): ALL four provider fields must be set.

    name, base_url (for custom/ollama — native providers have their own
    endpoint), api_key (unless the provider is keyless) and model. Returns
    (False, reason) naming the first gap so refusals and logs can say what
    is actually missing instead of a bare "no provider".
    """
    provider = config.provider
    name = provider.name.strip()
    if not name:
        return False, "provider.name is empty — pick a provider in Settings"
    if name in BASEURL_REQUIRED and not provider.base_url.strip():
        return False, f"provider.base_url is empty for {name!r}"
    if name not in KEYLESS_PROVIDERS and not provider.api_key.strip():
        return False, f"provider.api_key is empty for {name!r}"
    if not provider.model.strip():
        return False, "provider.model is empty — set Model Name in Settings"
    return True, ""


def build_llm_client(config: ArcenConfig) -> Any | None:
    """Build the LLM bridge from config — None when offline (no credential).

    Returns an arcen.llm.client.Client whose completion calls carry the
    provider's api_key / api_base. The credential lives only in process
    memory; it is never logged, never returned by the API.
    """
    # imported lazily — litellm import is heavy and tests may stub it
    from arcen.llm.client import Client

    ok, _reason = provider_ready(config)
    if not ok:
        return None  # incomplete provider → offline mode (degrade, never block)

    provider = config.provider
    resolved, _missing = resolve_secrets(
        {"api_key": provider.api_key, "base_url": provider.base_url}
    )
    api_key = str(resolved.get("api_key") or "").strip() or None
    base_url = str(resolved.get("base_url") or "").strip() or None

    if api_key and VAR_PATTERN.match(api_key):
        return None  # unresolved $VAR → the credential is absent (degraded)
    if not api_key and provider.name not in KEYLESS_PROVIDERS:
        return None  # no credential → offline mode (degrade, never block)

    prefix = LITELLM_PREFIX.get(provider.name, "")
    models: dict[str, str] = {}
    for role, agent in ROLE_AGENT_NAMES.items():
        name = model_for(agent, config)
        # T-053: only native providers (anthropic/openai) go bare. A custom
        # endpoint's model id may itself contain "/" (org/model) — routing
        # it un-prefixed makes LiteLLM guess the vendor instead of using the
        # configured api_base. Always through the namespace.
        models[role] = name if provider.name not in LITELLM_PREFIX else prefix + name

    def completion(**kwargs: Any):
        import litellm

        kwargs.setdefault("api_key", api_key)
        if base_url:
            kwargs.setdefault("api_base", base_url)
        return litellm.completion(**kwargs)

    return Client(models=models, completion_fn=completion)
