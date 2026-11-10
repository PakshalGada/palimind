"""Resolve an agent's model to a provider, endpoint, and capabilities.

One resolver is used by the direct chat route, the runtime, side questions, and
any future caller.  It never performs a completion and never stores a key on
the agent; provider secrets stay in the existing settings store.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from palimind.agents.providers.base import ProviderCapabilities


@dataclass(frozen=True)
class ResolvedModel:
    provider: str
    model: str
    base_url: str
    api_key: str | None = None
    capabilities: ProviderCapabilities = field(default_factory=ProviderCapabilities)
    source: str = "agent"
    error: str = ""
    action: str = ""
    message: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "capabilities": self.capabilities.as_dict(),
            "source": self.source,
            "error": self.error,
            "action": self.action,
            "message": self.message,
        }


def _capabilities(model: str, provider: str) -> ProviderCapabilities:
    try:
        from palimind.model_capabilities import infer_from_name

        caps = infer_from_name(model)
        return ProviderCapabilities(
            tools=True,
            vision=bool(getattr(caps, "supports_vision", False)),
            reasoning=bool(getattr(caps, "supports_reasoning", False)),
            streaming=True,
            usage=True,
            accounts=provider == "opencode",
            attachments=True,
            concurrent_turns=provider == "opencode",
            steering=False,
            context_window=int(getattr(caps, "context_window", 0) or 0),
        )
    except Exception:
        return ProviderCapabilities(tools=True, streaming=True, usage=True, attachments=True)


def _opencode_key() -> str:
    try:
        from palimind.opencode.auth import get_key

        return str(get_key("opencode") or "").strip()
    except Exception:
        return ""


def resolve_agent_model(
    definition: Any,
    *,
    global_chat_model: str = "",
    ollama_url: str = "http://localhost:11434",
) -> ResolvedModel:
    """Resolve ``AgentDefinition.provider`` + ``model``.

    Legacy agents have no provider: infer OpenCode by model id, exactly as the
    old router did.  A configured provider is authoritative, so a missing key
    or model is reported instead of silently running on another provider.
    """
    from palimind.opencode.router import (
        PROXY_URL,
        opencode_model_ids,
        resolve_model_url,
    )

    provider = str(getattr(definition, "provider", "") or "").strip().lower()
    model = str(getattr(definition, "model", "") or "").strip()
    fallback_model = str(global_chat_model or "").strip()
    if not model:
        model = fallback_model or "llama3"

    if provider in {"", "auto", "legacy"}:
        # Preserve the shipped behaviour for agents created before provider
        # became authoritative.
        try:
            inferred = "opencode" if model in opencode_model_ids() else "ollama"
        except Exception:
            inferred = "ollama"
        resolved_url = resolve_model_url(model, ollama_url)
        if resolved_url.rstrip("/") == PROXY_URL.rstrip("/"):
            inferred = "opencode"
        return ResolvedModel(
            provider=inferred,
            model=model,
            base_url=resolved_url,
            api_key=_opencode_key() if inferred == "opencode" else None,
            capabilities=_capabilities(model, inferred),
            source="legacy",
        )

    if provider == "opencode":
        key = _opencode_key()
        if not key:
            return ResolvedModel(
                provider="opencode",
                model=model,
                base_url=PROXY_URL,
                capabilities=_capabilities(model, "opencode"),
                source="agent",
                error="missing_key",
                action="add-key",
                message="OpenCode is selected for this agent, but no API key is saved.",
            )
        try:
            ids = opencode_model_ids()
        except Exception:
            ids = set()
        if ids and model not in ids:
            return ResolvedModel(
                provider="opencode",
                model=model,
                base_url=PROXY_URL,
                api_key=key,
                capabilities=_capabilities(model, "opencode"),
                source="agent",
                error="model_missing",
                action="choose-model",
                message=f"OpenCode does not list the model '{model}'.",
            )
        return ResolvedModel(
            provider="opencode",
            model=model,
            base_url=PROXY_URL,
            api_key=key,
            capabilities=_capabilities(model, "opencode"),
            source="agent",
        )

    if provider == "ollama":
        return ResolvedModel(
            provider="ollama",
            model=model,
            base_url=ollama_url,
            capabilities=_capabilities(model, "ollama"),
            source="agent",
        )

    # Custom OpenAI-compatible or ACP providers keep using their configured
    # endpoint; the runtime reads it from the provider adapter.
    return ResolvedModel(
        provider=provider,
        model=model,
        base_url=ollama_url,
        capabilities=_capabilities(model, provider),
        source="agent",
    )
