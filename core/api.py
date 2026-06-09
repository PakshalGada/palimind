"""
Public programmatic API for Palimind.

Import from here when building CLI, TUI, or GUI frontends. Core modules raise
domain exceptions; this module re-exports the main operations and result types.
"""
from __future__ import annotations

from core.exceptions import (
    CaptionError,
    EmbeddingError,
    ImageEncodeError,
    IndexExistsError,
    IndexNotFoundError,
    NoContextError,
    OCRError,
    PalimindError,
    ParseError,
    ResponseError,
)
from core.indexing import (
    extract_chunks,
    index_exists,
    initialize_index,
    require_index,
    update_index,
)
from core.models import (
    ChunkInfo,
    FileIndexError,
    InitIndexResult,
    ProgressCallback,
    QueryResult,
    QueryStream,
    RetrievedContext,
    UpdateIndexResult,
)
from core.querying import query, query_stream, retrieve

__all__ = [
    "CaptionError",
    "ChunkInfo",
    "EmbeddingError",
    "FileIndexError",
    "ImageEncodeError",
    "IndexExistsError",
    "IndexNotFoundError",
    "InitIndexResult",
    "NoContextError",
    "OCRError",
    "PalimindError",
    "ParseError",
    "ProgressCallback",
    "QueryResult",
    "QueryStream",
    "ResponseError",
    "RetrievedContext",
    "UpdateIndexResult",
    "extract_chunks",
    "index_exists",
    "initialize_index",
    "query",
    "query_stream",
    "require_index",
    "retrieve",
    "update_index",
]
