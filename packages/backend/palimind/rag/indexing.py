from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from palimind.config import load_config, palimind_dir, write_default_config
from palimind.core.embedder import generate_embeddings_batch
from palimind.exceptions import (
    CaptionError,
    EmbeddingError,
    IndexExistsError,
    IndexNotFoundError,
    OCRError,
    ParseError,
)
from palimind.generative.summariser import summarise_file
from palimind.ingestion.crawler import compute_md5, crawl_directory
from palimind.ingestion.doc_parser import parse_document
from palimind.ingestion.image_parser import caption_image
from palimind.ingestion.rich_chunker import (
    DocumentMeta,
    RichChunk,
    extract_doc_type,
    extract_doc_year,
    extract_entity_name,
    rich_chunk_caption,
    rich_chunk_document,
)
from palimind.models import (
    FileIndexError,
    InitIndexResult,
    ProgressCallback,
    UpdateIndexResult,
)
from palimind.storage.db import (
    delete_file,
    get_connection,
    init_db,
    insert_chunks,
    upsert_file,
    upsert_file_summary,
)
from palimind.storage.vector_store import VectorStore


def index_exists(root: Path) -> bool:
    return palimind_dir(root).exists()


def require_index(root: Path) -> Path:
    root = root.resolve()
    if not index_exists(root):
        raise IndexNotFoundError(f"No index found in {root}. Run init first.")
    return root


def initialize_index(root: Path, *, force: bool = False) -> InitIndexResult:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")

    p_dir = palimind_dir(root)
    if p_dir.exists() and not force:
        raise IndexExistsError(f"Index already exists at {p_dir}")

    write_default_config(root)
    init_db(root)
    return InitIndexResult(root=root, index_dir=p_dir, created=True)


def _build_doc_meta(file_path: Path, root: Path, text_sample: str) -> DocumentMeta:
    """Extract document metadata from filename and early text content."""
    rel_path = str(file_path.relative_to(root))
    filename = file_path.name
    doc_year = extract_doc_year(filename, text_sample)
    doc_type = extract_doc_type(filename, text_sample)
    entity_name = extract_entity_name(text_sample)
    return DocumentMeta(
        path=rel_path,
        doc_year=doc_year,
        doc_type=doc_type,
        entity_name=entity_name,
    )


def extract_chunks(file_path: Path, root: Path, config: dict) -> list[RichChunk]:
    """
    Parse *file_path* and return a list of :class:`RichChunk` objects.

    Video files → timestamped transcript chunks (ffmpeg + local whisper).
    Image files → single caption chunk.
    Documents/text → hierarchical rich chunks (section-aware).
    """
    ext = file_path.suffix.lower()

    if ext in config.get("video_extensions", []):
        return _extract_video_chunks(file_path, root, config)

    if ext in config["image_extensions"]:
        caption = caption_image(file_path, config["ollama_base_url"], config["vision_model"])
        if caption:
            rel_path = str(file_path.relative_to(root))
            meta = DocumentMeta(path=rel_path)
            return [rich_chunk_caption(caption, meta, chunk_index=0)]
        return []

    text = ""
    if ext in config["doc_extensions"]:
        try:
            text = parse_document(file_path)
        except ParseError:
            raise
        except Exception as e:
            raise ParseError(f"Error parsing document {file_path}: {e}") from e
    elif ext in config["extensions"]:
        try:
            text = file_path.read_text(encoding="utf-8")
        except OSError as e:
            raise ParseError(f"Error reading text file {file_path}: {e}") from e

    if not text:
        return []

    doc_meta = _build_doc_meta(file_path, root, text)
    return rich_chunk_document(
        text,
        doc_meta,
        chunk_size=config.get("chunk_size", 800),
        chunk_overlap=config.get("chunk_overlap", 150),
    )


def _extract_video_chunks(file_path: Path, root: Path, config: dict) -> list[RichChunk]:
    """Transcribe a video file and return timestamped transcript chunks."""
    import logging

    from palimind.ingestion.video_parser import parse_video

    logger = logging.getLogger(__name__)
    rel_path = str(file_path.relative_to(root))
    try:
        chunks_raw, _segments = parse_video(
            file_path,
            whisper_model=config.get("video_whisper_model", "base"),
            chunk_chars=config.get("video_chunk_chars", 800),
            max_chunk_seconds=float(config.get("video_chunk_seconds", 90)),
        )
    except RuntimeError as e:
        raise ParseError(f"Video indexing failed for {rel_path}: {e}") from e

    if not chunks_raw:
        logger.warning(f"No speech detected in video {rel_path}")
        return []

    meta = DocumentMeta(path=rel_path)
    rich_chunks: list[RichChunk] = []
    for i, seg in enumerate(chunks_raw):
        words = seg.text.split()
        chunk = RichChunk(
            content=seg.text,
            chunk_type="transcript",
            chunk_index=i,
            section_title=f"Transcript {i + 1}",
            parent_section="Transcript",
            main_section="Transcript",
            word_count=len(words),
            token_estimate=int(len(words) * 1.3),
            media_start_ts=seg.start,
            media_end_ts=seg.end,
        )
        # Apply shared document meta (doc_year/doc_type/entity from filename)
        chunk.doc_year = meta.doc_year
        chunk.fiscal_year = meta.doc_year
        chunk.doc_type = meta.doc_type or "video"
        chunk.entity_name = meta.entity_name
        rich_chunks.append(chunk)
    return rich_chunks


# ---------------------------------------------------------------------------
# Main index update
# ---------------------------------------------------------------------------


def update_index(
    root: Path,
    *,
    on_progress: ProgressCallback | None = None,
) -> UpdateIndexResult:
    from palimind.storage.db import INDEX_WRITE_LOCK

    with INDEX_WRITE_LOCK:
        return _update_index_locked(root, on_progress=on_progress)


def _update_index_locked(
    root: Path,
    *,
    on_progress: ProgressCallback | None = None,
) -> UpdateIndexResult:
    root = require_index(root)
    config = load_config(root)
    init_db(root)

    def report(
        phase: str, *, current: int = 0, total: int | None = None, message: str = ""
    ) -> None:
        if on_progress is not None:
            on_progress(phase, current=current, total=total, message=message)

    report("crawl", message="Scanning directory...")
    new_or_modified, unchanged, deleted, crawled_hashes = crawl_directory(root)
    report(
        "crawl",
        message=(
            f"Found {len(new_or_modified)} to index, "
            f"{len(unchanged)} unchanged, {len(deleted)} to delete"
        ),
    )

    conn = get_connection(root)
    file_errors: list[FileIndexError] = []
    chunks_indexed = 0
    indexed_files = 0

    try:
        with VectorStore(root) as vstore:
            # ---- deletions ----
            if deleted:
                for i, rel_path in enumerate(deleted, start=1):
                    vstore.delete_file(rel_path)
                    delete_file(conn, rel_path)
                    report("delete", current=i, total=len(deleted), message=rel_path)

            # ---- indexing ----
            # Files are processed concurrently: the per-file work (parse + embed +
            # summarise) is I/O-bound HTTP to Ollama, so a thread pool overlaps it
            # across files. All DB + vector-store writes stay on the main thread
            # (sequential → safe for the shared SQLite connection and VectorStore).
            max_workers = config.get("index_workers", 4)
            report_lock = threading.Lock()

            def process_file(
                fpath: Path, rel_path: str, idx: int, total: int, md5: str
            ) -> dict:
                """Parse + embed + summarise one file. Returns data for the DB write."""
                out: dict = {
                    "rel_path": rel_path,
                    "md5": "",
                    "error": None,
                    "no_chunks": False,
                    "first": None,
                    "db_chunks": [],
                    "valid_infos": [],
                    "summary": "",
                }

                # Reuse the hash computed during crawl; fall back to hashing here
                # only if it was somehow missing.
                if not md5:
                    md5 = compute_md5(fpath)
                if not md5:
                    out["error"] = "Could not compute file hash"
                    return out
                out["md5"] = md5

                try:
                    rich_chunks = extract_chunks(fpath, root, config)
                except (ParseError, CaptionError, OCRError) as e:
                    out["error"] = str(e)
                    return out

                if not rich_chunks:
                    out["no_chunks"] = True
                    return out

                out["first"] = rich_chunks[0]
                texts = [c.content for c in rich_chunks]

                # Embeddings and summary are independent LLM calls — run concurrently.
                with ThreadPoolExecutor(max_workers=2) as inner:
                    emb_future = inner.submit(
                        generate_embeddings_batch,
                        texts,
                        config["ollama_base_url"],
                        config["embed_model"],
                        root=root,
                    )
                    sum_future = None
                    if config.get("summarise", True):
                        with report_lock:
                            report("summarise", current=idx, total=total, message=rel_path)
                        sum_future = inner.submit(
                            summarise_file,
                            "\n\n".join(texts),
                            config["ollama_base_url"],
                            config["chat_model"],
                            max_chars=config.get("summary_max_chars", 8000),
                        )
                    try:
                        embeddings = emb_future.result()
                    except EmbeddingError as e:
                        out["error"] = str(e)
                        return out
                    out["summary"] = sum_future.result() if sum_future else ""

                db_chunks = []
                valid_infos: list[tuple[int, RichChunk, list[float]]] = []
                for ci, (chunk, emb) in enumerate(zip(rich_chunks, embeddings, strict=False)):
                    if not emb:
                        continue
                    db_chunks.append(
                        (
                            chunk.chunk_index,
                            chunk.chunk_type,
                            chunk.content,
                            chunk.section_title,
                            chunk.subsection,
                            chunk.parent_section,
                            chunk.page_number,
                            chunk.word_count,
                            chunk.token_estimate,
                            chunk.media_start_ts,
                            chunk.media_end_ts,
                        )
                    )
                    valid_infos.append((ci, chunk, emb))

                out["db_chunks"] = db_chunks
                out["valid_infos"] = valid_infos
                return out

            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                future_to_path: dict = {}
                for i, fpath in enumerate(new_or_modified, start=1):
                    rel_path = str(fpath.relative_to(root))
                    report("index", current=i, total=len(new_or_modified), message=rel_path)
                    vstore.delete_file(rel_path)
                    fut = pool.submit(
                        process_file,
                        fpath,
                        rel_path,
                        i,
                        len(new_or_modified),
                        crawled_hashes.get(rel_path, ""),
                    )
                    future_to_path[fut] = rel_path

                for fut in as_completed(future_to_path):
                    res = fut.result()
                    rel_path = res["rel_path"]

                    if res["error"]:
                        file_errors.append(FileIndexError(rel_path, res["error"]))
                        continue

                    if res["no_chunks"]:
                        # Upsert file record even if no chunks (so crawl knows it's indexed)
                        upsert_file(conn, rel_path, res["md5"], time.time())
                        continue

                    first = res["first"]
                    file_id = upsert_file(
                        conn,
                        rel_path,
                        res["md5"],
                        time.time(),
                        doc_year=first.doc_year,
                        doc_type=first.doc_type,
                        entity_name=first.entity_name,
                    )

                    if res["valid_infos"]:
                        chunk_db_ids = insert_chunks(conn, file_id, res["db_chunks"])

                        vector_data = [
                            {
                                "vector": emb,
                                "chunk_db_id": chunk_db_ids[j],
                                "file_path": rel_path,
                                "chunk_index": chunk.chunk_index,
                                "chunk_type": chunk.chunk_type,
                                "content": chunk.content,
                                "section_title": chunk.section_title,
                                "subsection": chunk.subsection,
                                "main_section": chunk.main_section,
                                "parent_section": chunk.parent_section,
                                "doc_year": chunk.doc_year,
                                "fiscal_year": chunk.fiscal_year or chunk.doc_year,
                                "doc_type": chunk.doc_type,
                                "entity_name": chunk.entity_name,
                                "media_start_ts": chunk.media_start_ts,
                                "media_end_ts": chunk.media_end_ts,
                            }
                            for j, (_, chunk, emb) in enumerate(res["valid_infos"])
                        ]
                        vstore.insert(vector_data)
                        chunks_indexed += len(vector_data)
                        indexed_files += 1

                    if res["summary"]:
                        upsert_file_summary(conn, rel_path, res["summary"])

            # Single commit for the whole batch.
            conn.commit()
    finally:
        conn.close()

    return UpdateIndexResult(
        indexed_files=indexed_files,
        deleted_files=len(deleted),
        unchanged_files=len(unchanged),
        chunks_indexed=chunks_indexed,
        file_errors=tuple(file_errors),
    )
