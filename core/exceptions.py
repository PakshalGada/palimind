"""Domain exceptions for Palimind. UI layers catch these and present messages."""
from __future__ import annotations


class PalimindError(Exception):
    """Base exception for recoverable Palimind failures."""


class IndexNotFoundError(PalimindError):
    """Raised when an operation requires an index that does not exist."""


class IndexExistsError(PalimindError):
    """Raised when initializing an index that already exists."""


class EmbeddingError(PalimindError):
    """Raised when Ollama embedding generation fails."""


class ParseError(PalimindError):
    """Raised when a document cannot be parsed."""


class CaptionError(PalimindError):
    """Raised when image captioning fails."""


class OCRError(PalimindError):
    """Raised when OCR fails."""


class ImageEncodeError(PalimindError):
    """Raised when an image cannot be encoded for the chat API."""


class ResponseError(PalimindError):
    """Raised when the chat/generate API fails."""


class NoContextError(PalimindError):
    """Raised when retrieval returns no usable context for a query."""
