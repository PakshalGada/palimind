from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol


class ProgressCallback(Protocol):
    def __call__(
        self,
        phase: str,
        *,
        current: int = 0,
        total: Optional[int] = None,
        message: str = "",
    ) -> None: ...


@dataclass(frozen=True)
class InitIndexResult:
    root: Path
    index_dir: Path
    created: bool


@dataclass(frozen=True)
class FileIndexError:
    path: str
    error: str


@dataclass(frozen=True)
class UpdateIndexResult:
    indexed_files: int
    deleted_files: int
    unchanged_files: int
    chunks_indexed: int
    file_errors: tuple[FileIndexError, ...] = ()


@dataclass(frozen=True)
class ChunkInfo:
    content: str
    chunk_type: str


@dataclass(frozen=True)
class RetrievedContext:
    text_contexts: tuple[str, ...]
    image_paths: tuple[str, ...]
    sources: tuple[str, ...]

    @property
    def has_context(self) -> bool:
        return bool(self.text_contexts or self.image_paths)


@dataclass(frozen=True)
class QueryResult:
    answer: str
    context: RetrievedContext
    query: str


QueryStream = tuple[RetrievedContext, Iterator[str]]
