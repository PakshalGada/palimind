"""Ollama provider adapter.

This is a thin wrapper over the existing Ollama client in
``palimind.llm.mixture_of_expert.llm``.  It does not replace the existing agent
loop; it gives the new provider boundary a stable implementation for the local
default.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from typing import Any

from palimind.agents.providers.base import (
    ProviderCapabilities,
    ProviderError,
    ProviderEvent,
    ProviderModel,
)


def _ollama_url() -> str:
    return os.environ.get("PALIMIND_OLLAMA_URL", "http://localhost:11434").rstrip("/")


class OllamaProvider:
    id = "ollama"
    capabilities = ProviderCapabilities(
        tools=True,
        vision=True,
        reasoning=False,
        streaming=True,
        usage=True,
        accounts=False,
        attachments=True,
        concurrent_turns=False,
        steering=False,
        context_window=8192,
    )

    async def list_models(self) -> list[ProviderModel]:
        from palimind.opencode.router import fetch_ollama_model_ids

        ids = await asyncio.to_thread(fetch_ollama_model_ids, _ollama_url())
        return [
            ProviderModel(
                id=model_id,
                provider=self.id,
                name=model_id,
                capabilities=self.capabilities,
                metadata={"local": True},
            )
            for model_id in sorted(ids)
        ]

    async def start_session(
        self,
        thread_id: str,
        *,
        model: str = "",
        system_prompt: str = "",
        tools: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        # Ollama is stateless; the thread id is the resume key.
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
        from palimind.llm.mixture_of_expert.llm import LLMError, llm_chat

        yield ProviderEvent("turn_started", {"session_id": session_id, "provider": self.id})
        try:
            result = await asyncio.to_thread(
                llm_chat,
                messages,
                model,
                _ollama_url(),
                tools=tools,
            )
        except LLMError as exc:
            cause = "timeout" if "timed out" in str(exc).lower() else "unknown"
            raise ProviderError(str(exc), cause=cause, retryable=bool(exc.transient)) from exc
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(str(exc), cause="network", retryable=True) from exc

        content = str(result.get("content") or "")
        for call in result.get("tool_calls") or []:
            yield ProviderEvent("tool_call", {"name": call.get("name"), "arguments": call.get("arguments") or {}})
        if content:
            yield ProviderEvent("message", {"text": content})
        usage = result.get("usage") or {}
        if usage:
            yield ProviderEvent("usage", dict(usage))
        yield ProviderEvent("turn_completed", {"session_id": session_id, "text": content})

    async def interrupt(self, session_id: str) -> None:
        # The HTTP call is not cancellable after it starts; the runtime cancels
        # the asyncio task. Nothing to release here.
        return None

    async def read_usage(self, session_id: str) -> dict[str, Any]:
        return {}

    async def close(self) -> None:
        return None
