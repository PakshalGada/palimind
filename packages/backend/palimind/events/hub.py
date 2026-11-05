"""Live subscriber fan-out for persisted SSE streams."""

from __future__ import annotations

import asyncio
from typing import Any

from palimind.events import store


class StreamHub:
    def __init__(self, *, queue_size: int = 2000) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()
        self._queue_size = max(10, int(queue_size or 2000))
        self._counts: dict[str, int] = {}

    async def publish(self, stream: str, event: dict[str, Any]) -> dict[str, Any]:
        """Persist an event, then fan it out to live subscribers."""
        stored = await asyncio.to_thread(store.append, stream, event)
        stream = str(stream)
        self._counts[stream] = self._counts.get(stream, 0) + 1
        if self._counts[stream] % 500 == 0:
            # Bound the log without blocking the producer's event loop.
            await asyncio.to_thread(store.prune, stream, 5000)
        async with self._lock:
            queues = list(self._subs.get(stream, ()))
        for queue in queues:
            try:
                queue.put_nowait(stored)
            except asyncio.QueueFull:
                # A slow client must not block the producer. The event is in
                # the log, so that client can recover with Last-Event-ID.
                pass
        return stored

    async def subscribe(self, stream: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._queue_size)
        async with self._lock:
            self._subs.setdefault(str(stream), set()).add(queue)
        return queue

    async def unsubscribe(self, stream: str, queue: asyncio.Queue) -> None:
        async with self._lock:
            queues = self._subs.get(str(stream))
            if not queues:
                return
            queues.discard(queue)
            if not queues:
                self._subs.pop(str(stream), None)

    async def has_subscribers(self, stream: str) -> bool:
        async with self._lock:
            return bool(self._subs.get(str(stream)))


hub = StreamHub()
