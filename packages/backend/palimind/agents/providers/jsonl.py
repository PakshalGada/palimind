"""Newline-delimited JSON-RPC over a child process.

Codex App Server and the Claude CLI stream JSONL rather than Content-Length
frames.  This transport is deliberately small: requests, notifications,
subscription queues, and clean shutdown.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from typing import Any

from palimind.agents.providers.base import ProviderError

logger = logging.getLogger(__name__)


class JSONLProcess:
    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        *,
        cwd: str = "",
        env: dict[str, str] | None = None,
        request_timeout: float = 120.0,
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
        self._lock = asyncio.Lock()

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
            raise ProviderError(
                f"could not start {self.command}: {exc}", cause="provider_unavailable"
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
            logger.debug("provider stderr: %s", line.decode("utf-8", "replace").rstrip())

    async def _reader_loop(self, stream: asyncio.StreamReader) -> None:
        while True:
            try:
                line = await stream.readline()
            except asyncio.CancelledError:
                raise
            if not line:
                break
            try:
                message = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            request_id = message.get("id")
            if request_id is not None and ("result" in message or "error" in message):
                future = self._pending.pop(int(request_id), None)
                if future is not None and not future.done():
                    future.set_result(message)
                continue
            for queue in list(self._queues):
                queue.put_nowait(message)
        for future in self._pending.values():
            if not future.done():
                future.set_exception(
                    ProviderError("provider process closed", cause="provider_unavailable")
                )
        self._pending.clear()
        for queue in list(self._queues):
            queue.put_nowait({"type": "__closed__"})

    async def send(self, message: dict[str, Any]) -> None:
        if self.process is None or self.process.stdin is None:
            raise ProviderError("provider process is not running", cause="provider_unavailable")
        async with self._lock:
            self.process.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
            await self.process.stdin.drain()

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self.send(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
        )
        try:
            response = await asyncio.wait_for(future, timeout=self.request_timeout)
        except TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise ProviderError(f"{method} timed out", cause="timeout", retryable=True) from exc
        if "error" in response:
            error = response.get("error") or {}
            raise ProviderError(str(error.get("message") or f"{method} failed"), cause="protocol")
        result = response.get("result")
        return result if isinstance(result, dict) else {"value": result}

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        await self.send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._queues.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._queues:
            self._queues.remove(queue)

    async def close(self) -> None:
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
