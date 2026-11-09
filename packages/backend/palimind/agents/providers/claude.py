"""Claude Code stream-json provider adapter.

The CLI is started with ``--output-format stream-json`` and
``--input-format stream-json``.  Messages are newline-delimited JSON; the
adapter maps assistant, tool, usage and result records to provider events.
"""

from __future__ import annotations

import asyncio
import os
import signal
import uuid
from collections.abc import AsyncIterator
from typing import Any

from palimind.agents.providers.base import (
    ProviderCapabilities,
    ProviderError,
    ProviderEvent,
    ProviderModel,
)
from palimind.agents.providers.jsonl import JSONLProcess

DEFAULT_ARGS = [
    "-p",
    "--output-format",
    "stream-json",
    "--input-format",
    "stream-json",
    "--verbose",
]


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


class ClaudeProvider:
    id = "claude"
    capabilities = ProviderCapabilities(
        tools=True,
        vision=True,
        reasoning=True,
        streaming=True,
        usage=True,
        accounts=True,
        attachments=True,
        concurrent_turns=False,
        steering=True,
        context_window=0,
    )

    def __init__(
        self,
        *,
        command: str = "",
        args: list[str] | None = None,
        cwd: str = "",
        env: dict[str, str] | None = None,
        request_timeout: float = 120.0,
    ) -> None:
        self.command = command or os.environ.get("PALIMIND_CLAUDE_COMMAND", "claude")
        self.args = args if args is not None else DEFAULT_ARGS
        self.cwd = cwd
        self.env = dict(env or {})
        self.request_timeout = request_timeout
        self.process: JSONLProcess | None = None
        self.session_id = ""
        self._sessions: dict[str, str] = {}
        self._usage: dict[str, dict[str, Any]] = {}
        self._started = False

    async def _start(self) -> JSONLProcess:
        if (
            self.process is not None
            and self.process.process is not None
            and self.process.process.returncode is None
        ):
            return self.process
        process = JSONLProcess(
            self.command,
            self.args,
            cwd=self.cwd,
            env=self.env,
            request_timeout=self.request_timeout,
        )
        await process.start()
        self.process = process
        self._started = True
        return process

    async def list_models(self) -> list[ProviderModel]:
        # Claude model names are provider-owned; the picker can use the
        # aliases the CLI documents. No process is started for this list.
        return [
            ProviderModel(
                id=model_id,
                provider=self.id,
                name=model_id,
                capabilities=self.capabilities,
                effort_levels=("low", "medium", "high", "xhigh", "max"),
                default_effort="medium",
            )
            for model_id in (
                "claude-sonnet-4-5",
                "claude-opus-4-5",
                "claude-haiku-4-5",
            )
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
        process = await self._start()
        session_id = self.session_id or f"claude:{thread_id}"
        self.session_id = session_id
        self._sessions[thread_id] = session_id
        # The CLI emits a system init record on its first turn. If the fixture
        # (or a future CLI) emits it at startup, adopt that id here.
        queue = process.subscribe()
        try:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=0.2)
                if (
                    isinstance(message, dict)
                    and message.get("type") == "system"
                    and message.get("subtype") == "init"
                ):
                    reported = str(message.get("session_id") or "")
                    if reported:
                        self.session_id = reported
                        self._sessions[thread_id] = reported
                        session_id = reported
            except TimeoutError:
                pass
        finally:
            process.unsubscribe(queue)
        return session_id

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
        await self._start()
        self.session_id = session_id
        self._sessions[thread_id] = session_id
        return session_id

    async def send_turn(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        *,
        model: str = "",
        effort: str = "",
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[ProviderEvent]:
        process = await self._start()
        queue = process.subscribe()
        content = [
            {"type": "text", "text": str(message.get("content") or "")}
            for message in messages
            if str(message.get("content") or "")
        ]
        payload: dict[str, Any] = {
            "type": "user",
            "message": {"role": "user", "content": content},
            "session_id": session_id,
        }
        yield ProviderEvent("turn_started", {"session_id": session_id, "provider": self.id})
        try:
            await process.send(payload)
            saw_text = False
            while True:
                message = await asyncio.wait_for(queue.get(), timeout=self.request_timeout)
                if message.get("type") == "__closed__":
                    raise ProviderError(
                        "Claude process closed during turn", cause="provider_unavailable"
                    )
                kind = str(message.get("type") or "")
                if kind == "system":
                    if message.get("subtype") == "init":
                        reported = str(message.get("session_id") or "")
                        if reported:
                            self.session_id = reported
                    continue
                if kind == "stream_event":
                    event = _as_dict(message.get("event"))
                    if event.get("type") == "content_block_delta":
                        delta = _as_dict(event.get("delta"))
                        text = str(delta.get("text") or "")
                        if text:
                            saw_text = True
                            yield ProviderEvent("message_delta", {"text": text})
                    continue
                if kind == "assistant":
                    body = (
                        message.get("message") if isinstance(message.get("message"), dict) else {}
                    )
                    for block in body.get("content") or []:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "text":
                            text = str(block.get("text") or "")
                            if text:
                                saw_text = True
                                yield ProviderEvent("message", {"text": text})
                        elif block.get("type") == "tool_use":
                            yield ProviderEvent(
                                "tool_call",
                                {
                                    "id": str(block.get("id") or ""),
                                    "name": str(block.get("name") or "tool"),
                                    "arguments": block.get("input") or {},
                                },
                            )
                    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
                    if usage:
                        value = {
                            "prompt_tokens": int(usage.get("input_tokens") or 0),
                            "completion_tokens": int(usage.get("output_tokens") or 0),
                        }
                        self._usage[session_id] = value
                        yield ProviderEvent("usage", value)
                    continue
                if kind == "user":
                    body = (
                        message.get("message") if isinstance(message.get("message"), dict) else {}
                    )
                    for block in body.get("content") or []:
                        if not isinstance(block, dict) or block.get("type") != "tool_result":
                            continue
                        yield ProviderEvent(
                            "tool_result",
                            {
                                "id": str(block.get("tool_use_id") or ""),
                                "status": "failed" if block.get("is_error") else "completed",
                                "content": _text(block.get("content")),
                            },
                        )
                    continue
                if kind == "result":
                    text = str(message.get("result") or "")
                    if text and not saw_text:
                        yield ProviderEvent("message", {"text": text})
                    usage = message.get("usage") if isinstance(message.get("usage"), dict) else {}
                    if usage:
                        value = {
                            "prompt_tokens": int(usage.get("input_tokens") or 0),
                            "completion_tokens": int(usage.get("output_tokens") or 0),
                        }
                        self._usage[session_id] = value
                        yield ProviderEvent("usage", value)
                    if message.get("subtype") not in (None, "success"):
                        raise ProviderError(
                            str(message.get("result") or "Claude turn failed"), cause="unknown"
                        )
                    yield ProviderEvent(
                        "turn_completed", {"session_id": session_id, "status": "completed"}
                    )
                    return
        finally:
            process.unsubscribe(queue)
        yield ProviderEvent("turn_completed", {"session_id": session_id})

    async def interrupt(self, session_id: str) -> None:
        process = self.process
        if process is None:
            return
        try:
            await process.send(
                {
                    "type": "control_request",
                    "request_id": str(uuid.uuid4()),
                    "request": {"subtype": "interrupt"},
                }
            )
        except Exception:  # noqa: BLE001
            if process.process is not None and process.process.returncode is None:
                try:
                    process.process.send_signal(signal.SIGINT)
                except Exception:
                    pass

    async def read_usage(self, session_id: str) -> dict[str, Any]:
        return dict(self._usage.get(session_id, {}))

    async def close(self) -> None:
        if self.process is not None:
            await self.process.close()
        self.process = None
        self._sessions.clear()
        self._usage.clear()
        self._started = False
