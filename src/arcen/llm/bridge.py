"""ARCEN — provider bridge: config → LLM client (T-031 / T-036).

The server used to hardcode ``DraftPlanner(llm=None)`` — every turn took
the deterministic fallback even when a provider was configured. This
module builds the real bridge from the validated config:

- resolves ``$VAR`` api-key indirection from the environment (Part 8);
- maps the configured provider onto LiteLLM model names
  (anthropic/openai bare; groq/deepseek/ollama/custom prefixed);
- returns ``None`` when no usable credential exists → offline mode,
  planning never blocks on a provider.

A missing credential degrades, it never crashes the boot (Part 8 rule 2).
"""

from __future__ import annotations

from typing import Any

from arcen.config import ArcenConfig, resolve_secrets

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


def build_llm_client(config: ArcenConfig) -> Any | None:
    """Build the LLM bridge from config — None when offline (no credential).

    Returns an arcen.llm.client.Client whose completion calls carry the
    provider's api_key / api_base. The credential lives only in process
    memory; it is never logged, never returned by the API.
    """
    # imported lazily — litellm import is heavy and tests may stub it
    from arcen.llm.client import Client

    provider = config.provider
    default = provider.default

    resolved, _missing = resolve_secrets(
        {"api_keys": provider.api_keys, "base_urls": provider.base_urls}
    )
    api_key = (resolved.get("api_keys") or {}).get(default) or None
    base_url = (resolved.get("base_urls") or {}).get(default) or None

    if not api_key and default not in KEYLESS_PROVIDERS:
        return None  # no credential → offline mode (degrade, never block)

    prefix = LITELLM_PREFIX.get(default, "")
    models: dict[str, str] = {}
    for role, name in provider.models.items():
        name = str(name)
        models[role] = name if "/" in name else prefix + name

    def completion(**kwargs: Any):
        import litellm

        kwargs.setdefault("api_key", api_key)
        if base_url:
            kwargs.setdefault("api_base", base_url)
        return litellm.completion(**kwargs)

    return Client(models=models, completion_fn=completion)
