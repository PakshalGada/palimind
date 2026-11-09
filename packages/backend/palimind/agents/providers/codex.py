"""Codex App Server provider adapter.

Codex exposes a newline-JSON RPC on ``codex app-server --listen stdio://``.
The adapter uses the small subset PaliMind needs: initialize, thread start or
resume, turn start, streaming item notifications, token usage, and interrupt.
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
from palimind.agents.providers.jsonl import JSONLProcess


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _item_text(item: dict[str, Any]) -> str:
    text = item.get("text")
    if isinstance(text, str):
        return text
    content = item.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
    return ""


def _item_tool_name(item: dict[str, Any]) -> str:
    return str(item.get("tool") or item.get("name") or item.get("type") or "tool")


class CodexProvider:
    id = "codex"
    capabilities = ProviderCapabilities(
        tools=True,
        vision=False,
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
        self.command = command or os.environ.get("PALIMIND_CODEX_COMMAND", "codex")
        self.args = args if args is not None else ["app-server", "--listen", "stdio://"]
        self.cwd = cwd
        self.env = dict(env or {})
        self.request_timeout = request_timeout
        self._sessions: dict[str, JSONLProcess] = {}
        self._threads: dict[str, str] = {}
        self._turns: dict[str, str] = {}
        self._usage: dict[str, dict[str, Any]] = {}
        self._initialized: set[int] = set()

    async def _process(self) -> JSONLProcess:
        process = self._sessions.get("main")
        if (
            process is not None
            and process.process is not None
            and process.process.returncode is None
        ):
            return process
        process = JSONLProcess(
            self.command,
            self.args,
            cwd=self.cwd,
            env=self.env,
            request_timeout=self.request_timeout,
        )
        await process.start()
        self._sessions["main"] = process
        self._initialized.clear()
        return process

    async def _initialize(self) -> JSONLProcess:
        process = await self._process()
        if id(process) not in self._initialized:
            try:
                await process.request(
                    "initialize",
                    {
                        "clientInfo": {"name": "PaliMind", "version": "1.0"},
                        "capabilities": {"experimental": False},
                    },
                )
            except ProviderError:
                pass
            try:
                await process.notify("initialized", {})
            except ProviderError:
                pass
            self._initialized.add(id(process))
        return process

    async def list_models(self) -> list[ProviderModel]:
        process = await self._initialize()
        try:
            result = await process.request("model/list", {})
        except ProviderError:
            return []
        raw = result.get("data")
        items: list[Any] = raw if isinstance(raw, list) else []
        out = []
        for item in items:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("model") or item.get("id") or "")
            if not model_id:
                continue
            efforts = [
                str(effort.get("reasoningEffort"))
                for effort in item.get("supportedReasoningEfforts") or []
                if isinstance(effort, dict) and effort.get("reasoningEffort")
            ]
            out.append(
                ProviderModel(
                    id=model_id,
                    provider=self.id,
                    name=str(item.get("displayName") or model_id),
                    capabilities=self.capabilities,
                    effort_levels=tuple(efforts),
                    default_effort=str(item.get("defaultReasoningEffort") or ""),
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
        process = await self._initialize()
        params: dict[str, Any] = {
            "cwd": self.cwd or os.getcwd(),
            "approvalPolicy": "on-request",
            "sandbox": "workspace-write",
            "ephemeral": False,
            "dynamicTools": tools or [],
        }
        if model:
            params["model"] = model
        if system_prompt:
            params["developerInstructions"] = system_prompt
        result = await process.request("thread/start", params)
        thread = _as_dict(result.get("thread"))
        provider_thread = str(thread.get("id") or "")
        if not provider_thread:
            raise ProviderError("thread/start returned no thread id", cause="protocol")
        self._threads[thread_id] = provider_thread
        return provider_thread

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
        process = await self._initialize()
        try:
            result = await process.request("thread/resume", {"threadId": session_id})
            thread = _as_dict(result.get("thread"))
            provider_thread = str(thread.get("id") or session_id)
            self._threads[thread_id] = provider_thread
            return provider_thread
        except ProviderError:
            return await self.start_session(
                thread_id, model=model, system_prompt=system_prompt, tools=tools, metadata=metadata
            )

    def _provider_thread(self, session_id: str) -> str:
        for key, value in self._threads.items():
            if value == session_id:
                return key
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
        process = await self._initialize()
        queue = process.subscribe()
        prompt = [
            {"type": "text", "text": str(message.get("content") or "")}
            for message in messages
            if str(message.get("content") or "")
        ]
        params: dict[str, Any] = {
            "threadId": session_id,
            "input": prompt,
            "cwd": self.cwd or os.getcwd(),
            "approvalPolicy": "on-request",
            "sandboxPolicy": "workspace-write",
        }
        if model:
            params["model"] = model
        if effort:
            params["effort"] = effort
        request = asyncio.create_task(process.request("turn/start", params))
        request_received = False
        yield ProviderEvent("turn_started", {"session_id": session_id, "provider": self.id})
        try:
            while True:
                get_task = asyncio.create_task(queue.get())
                waits = {get_task} if request_received else {get_task, request}
                done, pending = await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    if task is get_task:
                        task.cancel()
                if request in done and not request_received:
                    request_received = True
                    response = request.result()
                    turn = _as_dict(response.get("turn"))
                    if turn.get("id"):
                        self._turns[session_id] = str(turn["id"])
                    # Keep reading notifications; turn/completed ends the turn.
                    while not queue.empty():
                        event = self._event_from_notification(queue.get_nowait(), session_id)
                        if event is not None:
                            yield event
                            if event.type == "turn_completed":
                                return
                if get_task not in done:
                    continue
                message = get_task.result()
                if message.get("type") == "__closed__":
                    raise ProviderError(
                        "Codex app server closed during turn", cause="provider_unavailable"
                    )
                event = self._event_from_notification(message, session_id)
                if event is not None:
                    yield event
                    if event.type == "turn_completed":
                        return
        finally:
            process.unsubscribe(queue)
            if not request.done():
                request.cancel()
        yield ProviderEvent("turn_completed", {"session_id": session_id})

    def _event_from_notification(
        self, message: dict[str, Any], session_id: str
    ) -> ProviderEvent | None:
        method = str(message.get("method") or message.get("type") or "")
        params = _as_dict(message.get("params"))
        if method == "turn/started":
            turn = _as_dict(params.get("turn"))
            turn_id = str(turn.get("id") or "")
            if turn_id:
                self._turns[session_id] = turn_id
            return ProviderEvent("turn_started", {"session_id": session_id, "turn_id": turn_id})
        if method in ("item/agentMessage/delta", "item/agent_message/delta"):
            return ProviderEvent(
                "message_delta", {"text": str(params.get("delta") or params.get("text") or "")}
            )
        if method == "item/reasoning/summaryTextDelta":
            return ProviderEvent(
                "thought", {"text": str(params.get("delta") or params.get("text") or "")}
            )
        if method == "thread/tokenUsage/updated":
            usage = _as_dict(params.get("tokenUsage")) or params
            total = _as_dict(usage.get("total")) or usage
            value = {
                "prompt_tokens": int(total.get("inputTokens") or total.get("input_tokens") or 0),
                "completion_tokens": int(
                    total.get("outputTokens") or total.get("output_tokens") or 0
                ),
            }
            self._usage[session_id] = value
            return ProviderEvent("usage", value)
        if method in ("item/started", "item/completed"):
            item = _as_dict(params.get("item"))
            kind = str(item.get("type") or "")
            if kind == "agentMessage":
                text = _item_text(item)
                if text:
                    return ProviderEvent(
                        "message" if method == "item/completed" else "message_delta",
                        {"text": text},
                    )
            if kind == "reasoning":
                text = _item_text(item)
                if text:
                    return ProviderEvent("thought", {"text": text})
            if method == "item/started" and kind in (
                "commandExecution",
                "mcpToolCall",
                "fileChange",
                "webSearch",
            ):
                return ProviderEvent(
                    "tool_call",
                    {
                        "id": str(item.get("id") or ""),
                        "name": _item_tool_name(item),
                        "arguments": item.get("arguments") or item.get("input") or {},
                    },
                )
            if method == "item/completed" and kind in (
                "commandExecution",
                "mcpToolCall",
                "fileChange",
                "webSearch",
            ):
                return ProviderEvent(
                    "tool_result",
                    {
                        "id": str(item.get("id") or ""),
                        "status": str(item.get("status") or ""),
                        "content": str(
                            item.get("aggregatedOutput")
                            or item.get("output")
                            or item.get("result")
                            or ""
                        ),
                    },
                )
        if method == "turn/completed":
            turn = _as_dict(params.get("turn"))
            return ProviderEvent(
                "turn_completed",
                {
                    "session_id": session_id,
                    "turn_id": str(turn.get("id") or ""),
                    "status": str(turn.get("status") or ""),
                },
            )
        return None

    async def interrupt(self, session_id: str) -> None:
        process = await self._process()
        turn_id = self._turns.get(session_id, "")
        if turn_id:
            try:
                await process.request("turn/interrupt", {"threadId": session_id, "turnId": turn_id})
            except ProviderError:
                pass

    async def read_usage(self, session_id: str) -> dict[str, Any]:
        return dict(self._usage.get(session_id, {}))

    async def close(self) -> None:
        for process in list(self._sessions.values()):
            await process.close()
        self._sessions.clear()
        self._threads.clear()
        self._turns.clear()
        self._initialized.clear()
