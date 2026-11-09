"""Generic Agent Client Protocol (ACP) adapter.

ACP is JSON-RPC 2.0 over a child process's stdio.  The transport accepts both
newline-delimited JSON and the ``Content-Length`` framing used by LSP-style
servers.  The adapter normalizes streamed session updates into
:class:`~palimind.agents.providers.base.ProviderEvent` values.

Tests use ``tests/fixtures/acp_server.py`` instead of a real provider CLI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from palimind.agents.providers.base import (
    ProviderCapabilities,
    ProviderError,
    ProviderEvent,
    ProviderModel,
)

logger = logging.getLogger(__name__)


class ACPError(ProviderError):
    pass


async def _read_message(reader: asyncio.StreamReader) -> dict[str, Any] | None:
    line = await reader.readline()
    if not line:
        return None
    if line.lower().startswith(b"content-length:"):
        try:
            length = int(line.split(b":", 1)[1].strip())
        except (IndexError, ValueError):
            return None
        await reader.readline()  # blank separator
        body = await reader.readexactly(length)
        return json.loads(body.decode("utf-8"))
    try:
        value = json.loads(line.decode("utf-8"))
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        return None


def _frame(message: dict[str, Any]) -> bytes:
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


class ACPSession:
    """One ACP child process and its JSON-RPC state."""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        *,
        cwd: str = "",
        env: dict[str, str] | None = None,
        request_timeout: float = 60.0,
    ) -> None:
        self.command = command
        self.args = list(args or [])
        self.cwd = cwd or None
        self.env = {**os.environ, **(env or {})}
        self.request_timeout = request_timeout
        self.process: asyncio.subprocess.Process | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._queues: list[asyncio.Queue] = []
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._write_lock = asyncio.Lock()
        self._closed = False
        self.provider_session_id = ""

    async def start(self) -> None:
        resolved = shutil.which(self.command) or self.command
        try:
            self.process = await asyncio.create_subprocess_exec(
                resolved,
                *self.args,
                cwd=self.cwd,
                env=self.env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as exc:  # noqa: BLE001
            raise ACPError(
                f"could not start ACP process: {exc}", cause="provider_unavailable"
            ) from exc
        assert self.process.stdout is not None
        assert self.process.stderr is not None
        self._reader_task = asyncio.create_task(self._reader_loop(self.process.stdout))
        self._stderr_task = asyncio.create_task(self._drain_stderr(self.process.stderr))

    async def _drain_stderr(self, stream: asyncio.StreamReader) -> None:
        while True:
            line = await stream.readline()
            if not line:
                return
            logger.debug("acp stderr: %s", line.decode("utf-8", "replace").rstrip())

    async def _reader_loop(self, stream: asyncio.StreamReader) -> None:
        while True:
            try:
                message = await _read_message(stream)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("ACP read failed: %s", exc)
                message = None
            if message is None:
                break
            request_id = message.get("id")
            if request_id is not None and ("result" in message or "error" in message):
                future = self._pending.pop(int(request_id), None)
                if future is not None and not future.done():
                    future.set_result(message)
                continue
            if request_id is not None and "method" in message:
                # Server-to-client request: answer unsupported methods so the
                # provider does not hang. Permission handling is normalized by
                # the runtime adapter when it is available.
                await self._send(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32601, "message": "method not supported by PaliMind"},
                    }
                )
                continue
            for queue in list(self._queues):
                queue.put_nowait(message)
        for future in self._pending.values():
            if not future.done():
                future.set_exception(ACPError("ACP process closed", cause="provider_unavailable"))
        self._pending.clear()
        for queue in list(self._queues):
            queue.put_nowait({"type": "__closed__"})

    async def _send(self, message: dict[str, Any]) -> None:
        if self.process is None or self.process.stdin is None:
            raise ACPError("ACP process is not running", cause="provider_unavailable")
        async with self._write_lock:
            self.process.stdin.write(_frame(message))
            await self.process.stdin.drain()

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self._send(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
        )
        try:
            response = await asyncio.wait_for(future, timeout=self.request_timeout)
        except TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise ACPError(
                f"ACP request timed out: {method}", cause="timeout", retryable=True
            ) from exc
        if "error" in response:
            error = response.get("error") or {}
            raise ACPError(
                str(error.get("message") or f"ACP {method} failed"),
                cause="protocol",
            )
        result = response.get("result")
        return result if isinstance(result, dict) else {"value": result}

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._queues.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._queues:
            self._queues.remove(queue)

    async def close(self) -> None:
        self._closed = True
        if self._reader_task is not None:
            self._reader_task.cancel()
        if self._stderr_task is not None:
            self._stderr_task.cancel()
        if self.process is not None and self.process.returncode is None:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=3.0)
            except Exception:  # noqa: BLE001
                try:
                    self.process.kill()
                except Exception:
                    pass


def _text_from_update(update: dict[str, Any]) -> str:
    content = update.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return str(content.get("text") or "")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
        return "".join(parts)
    return ""


def normalize_update(update: dict[str, Any]) -> ProviderEvent | None:
    """Turn one ACP ``session/update`` payload into a provider event."""
    kind = str(update.get("sessionUpdate") or update.get("type") or "")
    if kind in ("agent_message_chunk", "agent_message"):
        return ProviderEvent("message_delta", {"text": _text_from_update(update)})
    if kind in ("agent_thought_chunk", "agent_thought"):
        return ProviderEvent("thought", {"text": _text_from_update(update)})
    if kind in ("tool_call", "tool_call_start"):
        return ProviderEvent(
            "tool_call",
            {
                "id": update.get("toolCallId") or update.get("id") or "",
                "name": update.get("title") or update.get("kind") or "tool",
                "arguments": update.get("rawInput") or update.get("input") or {},
            },
        )
    if kind in ("tool_call_update", "tool_call_end"):
        return ProviderEvent(
            "tool_result",
            {
                "id": update.get("toolCallId") or update.get("id") or "",
                "status": update.get("status") or "",
                "content": _text_from_update(update) or update.get("rawOutput") or "",
            },
        )
    if kind in ("usage_update", "usage"):
        raw_usage = update.get("usage")
        usage = raw_usage if isinstance(raw_usage, dict) else update
        return ProviderEvent(
            "usage",
            {
                "prompt_tokens": int(usage.get("inputTokens") or usage.get("prompt_tokens") or 0),
                "completion_tokens": int(
                    usage.get("outputTokens") or usage.get("completion_tokens") or 0
                ),
            },
        )
    if kind in ("available_commands_update", "current_mode_update", "config_option_update"):
        return ProviderEvent("provider_update", {"kind": kind, "update": update})
    return None


class ACPProvider:
    """A provider backed by one ACP command."""

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
        provider_id: str = "acp",
        *,
        command: str = "",
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str = "",
        request_timeout: float = 120.0,
        session_factory: Callable[[], Awaitable[ACPSession]] | None = None,
    ) -> None:
        self.id = provider_id
        self.command = command or os.environ.get("PALIMIND_ACP_COMMAND", "")
        self.args = list(args or [])
        self.env = dict(env or {})
        self.cwd = cwd
        self.request_timeout = request_timeout
        self.session_factory = session_factory
        self._sessions: dict[str, ACPSession] = {}
        self._initialized: set[int] = set()

    async def _session(self, thread_id: str) -> ACPSession:
        session = self._sessions.get(thread_id)
        if (
            session is not None
            and session.process is not None
            and session.process.returncode is None
        ):
            return session
        if self.session_factory is not None:
            session = await self.session_factory()
        else:
            if not self.command:
                raise ACPError(
                    "PALIMIND_ACP_COMMAND is not set", cause="authentication", retryable=False
                )
            session = ACPSession(
                self.command,
                self.args,
                cwd=self.cwd,
                env=self.env,
                request_timeout=self.request_timeout,
            )
        await session.start()
        self._sessions[thread_id] = session
        return session

    async def _initialize(self, session: ACPSession) -> None:
        if id(session) in self._initialized:
            return
        try:
            await session.request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": False, "writeTextFile": False},
                        "terminal": False,
                    },
                    "clientInfo": {"name": "PaliMind", "version": "1.0"},
                },
            )
        except ACPError:
            # Some servers do not require initialize. Continue to session/new.
            pass
        self._initialized.add(id(session))

    async def list_models(self) -> list[ProviderModel]:
        if not self.command and self.session_factory is None:
            return []
        session = await self._session("__models__")
        try:
            await self._initialize(session)
            result = await session.request("models/list", {})
            raw_models = result.get("models")
            models: list[Any] = raw_models if isinstance(raw_models, list) else []
        except ACPError:
            models = []
        out = []
        for item in models:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or item.get("modelId") or "")
            if not model_id:
                continue
            out.append(
                ProviderModel(
                    id=model_id,
                    provider=self.id,
                    name=str(item.get("name") or model_id),
                    capabilities=self.capabilities,
                    effort_levels=tuple(item.get("effortLevels") or ()),
                    default_effort=str(item.get("defaultEffort") or ""),
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
        session = await self._session(thread_id)
        await self._initialize(session)
        params: dict[str, Any] = {"cwd": self.cwd or os.getcwd(), "mcpServers": []}
        if model:
            params["model"] = model
        if system_prompt:
            params["systemPrompt"] = system_prompt
        result = await session.request("session/new", params)
        session_id = str(result.get("sessionId") or result.get("session_id") or "")
        if not session_id:
            raise ACPError("ACP session/new returned no session id", cause="protocol")
        session.provider_session_id = session_id
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
        session = await self._session(thread_id)
        await self._initialize(session)
        try:
            await session.request("session/load", {"sessionId": session_id})
            session.provider_session_id = session_id
            return session_id
        except ACPError:
            return await self.start_session(
                thread_id,
                model=model,
                system_prompt=system_prompt,
                tools=tools,
                metadata=metadata,
            )

    async def send_turn(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        *,
        model: str = "",
        effort: str = "",
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[ProviderEvent]:
        session = next(
            (s for s in self._sessions.values() if s.provider_session_id == session_id), None
        )
        if session is None:
            raise ACPError(f"unknown ACP session: {session_id}", cause="protocol")
        await self._initialize(session)
        queue = session.subscribe()
        prompt_parts = []
        for message in messages:
            role = str(message.get("role") or "user")
            content = str(message.get("content") or "")
            if content:
                prompt_parts.append({"type": "text", "text": content, "role": role})
        params: dict[str, Any] = {"sessionId": session_id, "prompt": prompt_parts}
        if model:
            params["model"] = model
        if effort:
            params["effort"] = effort

        request = asyncio.create_task(session.request("session/prompt", params))
        yield ProviderEvent("turn_started", {"session_id": session_id, "provider": self.id})
        try:
            while True:
                get_task = asyncio.create_task(queue.get())
                done, pending = await asyncio.wait(
                    {get_task, request}, return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    if task is get_task:
                        task.cancel()
                if request in done:
                    if get_task in done:
                        # Drain a notification that arrived with the response.
                        message = get_task.result()
                        event = self._event_from_message(message)
                        if event is not None:
                            yield event
                    # The reader may have queued several updates before the
                    # response completed. Flush them so usage and final tool
                    # results are never lost.
                    while not queue.empty():
                        event = self._event_from_message(queue.get_nowait())
                        if event is not None:
                            yield event
                    response = request.result()
                    text = str(response.get("text") or response.get("output") or "")
                    if text:
                        yield ProviderEvent("message", {"text": text})
                    break
                message = get_task.result()
                if message.get("type") == "__closed__":
                    raise ACPError("ACP process closed during turn", cause="provider_unavailable")
                event = self._event_from_message(message)
                if event is not None:
                    yield event
        finally:
            session.unsubscribe(queue)
            if not request.done():
                request.cancel()
        yield ProviderEvent("turn_completed", {"session_id": session_id})

    def _event_from_message(self, message: dict[str, Any]) -> ProviderEvent | None:
        if message.get("method") not in (None, "session/update"):
            return None
        raw_params = message.get("params")
        params: dict[str, Any] = raw_params if isinstance(raw_params, dict) else message
        raw_update = params.get("update")
        update = raw_update if isinstance(raw_update, dict) else params
        if not isinstance(update, dict):
            return None
        return normalize_update(update)

    async def interrupt(self, session_id: str) -> None:
        session = next(
            (s for s in self._sessions.values() if s.provider_session_id == session_id), None
        )
        if session is not None:
            await session.notify("session/cancel", {"sessionId": session_id})

    async def read_usage(self, session_id: str) -> dict[str, Any]:
        return {}

    async def close(self) -> None:
        for session in list(self._sessions.values()):
            await session.close()
        self._sessions.clear()
        self._initialized.clear()
