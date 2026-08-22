from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path

from core.document.engine import DocumentEngine

logger = logging.getLogger(__name__)


async def run_chat_pipeline(
    query: str,
    field_path: str,
    mode: str = "document",
    engine: "DocumentEngine | None" = None,
) -> "asyncio.AsyncIterator[str]":
    """Run the host's real document-RAG pipeline for a guest query.

    Yields answer tokens as plain text chunks. Retrieval is rooted strictly
    at ``field_path``: the DocumentEngine used here is bound to that folder
    only, so a guest can never reach the host's other Palispaces. Pass a
    cached ``engine`` (e.g. ``session.get_engine()``) to avoid rebuilding
    per query.

    The pipeline (retrieval + generation) is blocking, so it runs in a
    thread executor; chunks are fed back over an asyncio.Queue so the event
    loop is never blocked. ``mode`` is reserved for future modes; only
    "document" is supported for now.
    """
    logger.debug("[TEAMS] run_chat_pipeline entry (field=%s)", field_path)
    if mode != "document":
        logger.warning("[TEAMS] unsupported mode %r, falling back to document", mode)

    if engine is None:
        engine = DocumentEngine(Path(field_path))
    queue: "asyncio.Queue[tuple[str, str | None]]" = asyncio.Queue()
    stop = threading.Event()
    loop = asyncio.get_running_loop()

    def _emit(kind: str, value: str | None) -> None:
        # asyncio.Queue is not thread-safe; schedule the put on the loop.
        loop.call_soon_threadsafe(queue.put_nowait, (kind, value))

    def _run() -> None:
        try:
            context = engine.retrieve_context(query, limit=15)
            for token in engine.stream_answer(query, context):
                if stop.is_set():
                    return
                _emit("token", token)
            _emit("end", None)
        except Exception as e:
            logger.warning("[TEAMS] pipeline error: %s", e)
            _emit("error", str(e))

    task = loop.run_in_executor(None, _run)

    try:
        while True:
            kind, value = await queue.get()
            if kind == "token":
                yield value
            elif kind == "error":
                yield f"**Error:** {value}"
                break
            else:
                break
    finally:
        stop.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        logger.debug("[TEAMS] run_chat_pipeline exit")