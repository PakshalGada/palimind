from dataclasses import dataclass

DEFAULT_CHUNK_SIZE = 1000
DEFAULT_OVERLAP = 200


@dataclass
class Chunk:
    text: str
    source_path: str
    start_char: int
    end_char: int


def _snap_to_word_boundary(text: str, pos: int) -> int:
    """Walk backwards from pos to the nearest space or newline."""
    if pos >= len(text):
        return len(text)
    while pos > 0 and text[pos] not in (" ", "\n", "\r", "\t"):
        pos -= 1
    return pos


def chunk_text(
    text: str,
    source_path: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[Chunk]:
    """Split text into overlapping chunks without cutting mid-word."""
    if not text.strip():
        return []

    chunks: list[Chunk] = []
    stride = chunk_size - overlap
    start = 0

    while start < len(text):
        raw_end = start + chunk_size

        if raw_end >= len(text):
            end = len(text)
        else:
            end = _snap_to_word_boundary(text, raw_end)
            # If snap walked all the way back to start, force-advance to avoid
            # an infinite loop on pathological inputs (e.g. one giant token).
            if end <= start:
                end = raw_end

        chunk_str = text[start:end]
        if chunk_str.strip():
            chunks.append(
                Chunk(
                    text=chunk_str,
                    source_path=source_path,
                    start_char=start,
                    end_char=end,
                )
            )

        if end >= len(text):
            break

        start += stride

    return chunks
