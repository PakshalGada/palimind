"""Generic OpenAI-compatible provider adapter.

Useful for hosted fallbacks, LM Studio, vLLM, and local gateways.  The endpoint
and key come from the environment or from an agent/provider configuration; the
adapter never writes them to SQLite.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

from palimind.agents.providers.base import (
    ProviderCapabilities,
    ProviderError,
    ProviderEvent,
    ProviderModel,
)


def _base_url() -> str:
    return os.environ.get("PALIMIND_OPENAI_BASE_URL", "").rstrip("/")


def _api_key() -> str:
    return os.environ.get("PALIMIND_OPENAI_API_KEY", "").strip()


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = _api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


class OpenAICompatibleProvider:
    id = "openai"
    capabilities = ProviderCapabilities(
        tools=True,
        vision=True,
        reasoning=True,
        streaming=False,
        usage=True,
        accounts=False,
        attachments=True,
        concurrent_turns=True,
        steering=False,
        context_window=0,
    )

    async def list_models(self) -> list[ProviderModel]:
        base = _base_url()
        if not base:
            return []
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{base}/models", headers=_headers())
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"OpenAI-compatible model list failed: {exc}", cause="network") from exc
        out: list[ProviderModel] = []
        for item in data.get("data") or []:
            model_id = str(item.get("id") or "")
            if not model_id:
                continue
            out.append(
                ProviderModel(
                    id=model_id,
                    provider=self.id,
                    name=str(item.get("name") or model_id),
                    capabilities=self.capabilities,
                    metadata={"endpoint": base},
                )
            )
        return out

    async def start_session(
        self,
        thread_id: str,
        *,
        model: str = "",
        system_prompt: str = "",
        tools: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        return thread_id

    async def resume_session(
        self,
        thread_id: str,
        session_id: str,
        *,
        model: str = "",
        system_prompt: str = "",
        tools: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        return session_id or thread_id

    async def send_turn(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        *,
        model: str = "",
        effort: str = "",
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[ProviderEvent]:
        base = _base_url()
        if not base:
            raise ProviderError(
                "PALIMIND_OPENAI_BASE_URL is not set", cause="authentication", retryable=False
            )
        import httpx

        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
        if tools:
            payload["tools"] = tools
        yield ProviderEvent("turn_started", {"session_id": session_id, "provider": self.id})
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{base}/chat/completions", headers=_headers(), json=payload
                )
                if resp.status_code in (401, 403):
                    raise ProviderError("OpenAI-compatible authentication failed", cause="authentication")
                if resp.status_code == 429:
                    raise ProviderError("OpenAI-compatible rate limit", cause="rate_limit", retryable=True)
                if resp.status_code >= 500:
                    raise ProviderError(
                        f"OpenAI-compatible server error: {resp.status_code}",
                        cause="provider_unavailable",
                        retryable=True,
                    )
                resp.raise_for_status()
                data = resp.json()
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(str(exc), cause="network", retryable=True) from exc

        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        for call in message.get("tool_calls") or []:
            fn = call.get("function") or {}
            yield ProviderEvent(
                "tool_call", {"name": fn.get("name"), "arguments": fn.get("arguments") or {}}
            )
        content = str(message.get("content") or "")
        if content:
            yield ProviderEvent("message", {"text": content})
        usage = data.get("usage") or {}
        if usage:
            yield ProviderEvent(
                "usage",
                {
                    "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                    "completion_tokens": int(usage.get("completion_tokens") or 0),
                },
            )
        yield ProviderEvent("turn_completed", {"session_id": session_id, "text": content})

    async def interrupt(self, session_id: str) -> None:
        return None

    async def read_usage(self, session_id: str) -> dict[str, Any]:
        return {}

    async def close(self) -> None:
        return None
