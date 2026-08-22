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
) -> "asyncio.AsyncIterator[str]":
    """Run the host's real document-RAG pipeline for a guest query.

    Yields answer tokens as plain text chunks. Retrieval is rooted strictly
    at ``field_path``: a fresh DocumentEngine is constructed for that folder
    only, so a guest can never reach the host's other Palispaces.

    The pipeline (retrieval + generation) is blocking, so it runs in a
    thread executor; chunks are fed back over an asyncio.Queue so the event
    loop is never blocked. ``mode`` is reserved for future modes; only
    "document" is supported for now.
    """
    logger.debug("[TEAMS] run_chat_pipeline entry (field=%s)", field_path)
    if mode != "document":
        logger.warning("[TEAMS] unsupported mode %r, falling back to document", mode)

    engine = DocumentEngine(Path(field_path))
    queue: "asyncio.Queue[tuple[str, str | None]]" = asyncio.Queue()
    stop = threading.Event()

    def _run() -> None:
        try:
            context = engine.retrieve_context(query, limit=15)
            for token in engine.stream_answer(query, context):
                if stop.is_set():
                    return
                queue.put_nowait(("token", token))
            queue.put_nowait(("end", None))
        except Exception as e:
            logger.warning("[TEAMS] pipeline error: %s", e)
            queue.put_nowait(("error", str(e)))

    loop = asyncio.get_running_loop()
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