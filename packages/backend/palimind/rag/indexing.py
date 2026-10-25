from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from palimind.config import load_config, palimind_dir, write_default_config
from palimind.core.embedder import generate_embeddings_batch, prewarm_cache
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
from palimind.storage.vector_store import VectorStore, index_load_error, write_stamp
from palimind.storage.vector_store import reset as reset_vector_store


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
    source_root: Path | None = None,
) -> UpdateIndexResult:
    """Update the index stored in *root*.

    ``source_root`` optionally indexes a different directory (a project's
    workspace) into this store. When omitted, content and index share *root*
    exactly as before.
    """
    from palimind.storage.db import INDEX_WRITE_LOCK

    with INDEX_WRITE_LOCK:
        return _update_index_locked(root, on_progress=on_progress, source_root=source_root)


def _update_index_locked(
    root: Path,
    *,
    on_progress: ProgressCallback | None = None,
    source_root: Path | None = None,
) -> UpdateIndexResult:
    root = require_index(root)
    scan_root = (source_root or root).resolve()
    if not scan_root.is_dir():
        raise ValueError(f"Not a directory: {scan_root}")
    config = load_config(root)
    init_db(root)

    def report(
        phase: str, *, current: int = 0, total: int | None = None, message: str = ""
    ) -> None:
        if on_progress is not None:
            on_progress(phase, current=current, total=total, message=message)

    # A persisted index written by an older/incompatible build cannot be
    # decoded, and an index built with a different embedding model must not be
    # mixed with new vectors. In either case discard it plus the cached file
    # hashes so every file is re-embedded and the store is rebuilt from scratch.
    index_error = index_load_error(root, expected_model=config.get("embed_model"))
    if index_error:
        report("crawl", message="Vector index incompatible — rebuilding from scratch...")
        reset_vector_store(root)
        reset_conn = get_connection(root)
        try:
            reset_conn.execute("DELETE FROM entity_mentions")
            reset_conn.execute("DELETE FROM chunks")
            reset_conn.execute("DELETE FROM files")
            reset_conn.commit()
        finally:
            reset_conn.close()

    report("crawl", message="Scanning directory...")
    new_or_modified, unchanged, deleted, crawled_hashes = crawl_directory(
        scan_root, index_root=root, config=config
    )
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
    detected_dim: dict[str, int] = {}

    try:
        with VectorStore(root, quantization=config.get("vector_quantization", "none")) as vstore:
            # ---- deletions ----
            if deleted:
                for i, rel_path in enumerate(deleted, start=1):
                    vstore.delete_file(rel_path)
                    delete_file(conn, rel_path)
                    report("delete", current=i, total=len(deleted), message=rel_path)

            # ---- indexing ----
            # Streaming approach: process files in batches, commit after each batch.
            # This gives progressive results — if interrupted, partial results are saved.
            #
            # For each batch:
            #   1. Parse files concurrently (I/O-bound: read + parse)
            #   2. One batch embedding call for all chunks in the batch
            #   3. Distribute embeddings, write to DB + vector store
            #   4. Commit
            #
            # Large files (>20 chunks) get their text split into sections processed
            # concurrently for faster chunking.
            max_workers = config.get("index_workers", 8)
            batch_size = config.get("index_batch_size", 5)
            report_lock = threading.Lock()

            prewarm_cache(root)

            def parse_file(fpath: Path, rel_path: str, idx: int, total: int, md5: str) -> dict:
                """Parse one file (+ optional summary). Returns data for later phases."""
                out: dict = {
                    "rel_path": rel_path,
                    "md5": "",
                    "error": None,
                    "no_chunks": False,
                    "first": None,
                    "rich_chunks": [],
                    "summary": "",
                }

                if not md5:
                    md5 = compute_md5(fpath)
                if not md5:
                    out["error"] = "Could not compute file hash"
                    return out
                out["md5"] = md5

                try:
                    rich_chunks = extract_chunks(fpath, scan_root, config)
                except (ParseError, CaptionError, OCRError) as e:
                    out["error"] = str(e)
                    return out

                if not rich_chunks:
                    out["no_chunks"] = True
                    return out

                out["first"] = rich_chunks[0]
                out["rich_chunks"] = rich_chunks

                if config.get("summarise", False):
                    with report_lock:
                        report("summarise", current=idx, total=total, message=rel_path)
                    texts = [c.content for c in rich_chunks]
                    out["summary"] = summarise_file(
                        "\n\n".join(texts),
                        config["ollama_base_url"],
                        config["chat_model"],
                        max_chars=config.get("summary_max_chars", 8000),
                    )

                return out

            def process_batch(batch: list[tuple[int, Path, str, str]]) -> None:
                """Parse + embed + write one batch of files, then commit."""
                nonlocal chunks_indexed, indexed_files
                parse_results: list[dict] = []

                # Parse batch concurrently
                with ThreadPoolExecutor(max_workers=max_workers) as pool:
                    future_to_info: dict = {}
                    for i, fpath, rel_path, md5 in batch:
                        report("index", current=i, total=len(new_or_modified), message=rel_path)
                        vstore.delete_file(rel_path)
                        fut = pool.submit(parse_file, fpath, rel_path, i, len(new_or_modified), md5)
                        future_to_info[fut] = rel_path

                    for fut in as_completed(future_to_info):
                        parse_results.append(fut.result())

                # Collect all texts for batch embedding
                all_texts: list[str] = []
                file_spans: list[tuple[int, int, int]] = []  # (result_idx, start, end)
                for i, result in enumerate(parse_results):
                    if result["error"] or result["no_chunks"] or not result["rich_chunks"]:
                        continue
                    start = len(all_texts)
                    all_texts.extend(c.content for c in result["rich_chunks"])
                    file_spans.append((i, start, len(all_texts)))

                # Batch embedding — one HTTP call for the entire batch
                all_embeddings: list[list[float]] = []
                if all_texts:
                    report(
                        "embed",
                        message=f"Embedding {len(all_texts)} chunks from {len(file_spans)} files...",
                    )
                    try:
                        all_embeddings = generate_embeddings_batch(
                            all_texts,
                            config["ollama_base_url"],
                            config["embed_model"],
                            root=root,
                        )
                    except EmbeddingError as e:
                        for result_idx, _, _ in file_spans:
                            result = parse_results[result_idx]
                            file_errors.append(FileIndexError(result["rel_path"], str(e)))
                        all_embeddings = []

                if all_embeddings and not detected_dim:
                    detected_dim["dim"] = len(all_embeddings[0])

                # Distribute embeddings and write to DB (main thread)
                for result_idx, start, end in file_spans:
                    result = parse_results[result_idx]
                    if result["error"]:
                        continue

                    embeddings = all_embeddings[start:end]
                    rich_chunks = result["rich_chunks"]

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

                    first = result["first"]
                    file_id = upsert_file(
                        conn,
                        result["rel_path"],
                        result["md5"],
                        time.time(),
                        doc_year=first.doc_year,
                        doc_type=first.doc_type,
                        entity_name=first.entity_name,
                    )

                    if valid_infos:
                        chunk_db_ids = insert_chunks(conn, file_id, db_chunks)

                        vector_data = [
                            {
                                "vector": emb,
                                "chunk_db_id": chunk_db_ids[j],
                                "file_path": result["rel_path"],
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
                            for j, (_, chunk, emb) in enumerate(valid_infos)
                        ]
                        vstore.insert(vector_data)
                        chunks_indexed += len(vector_data)
                        indexed_files += 1

                    if result["summary"]:
                        upsert_file_summary(conn, result["rel_path"], result["summary"])

                # Handle no-chunks and error results
                for result in parse_results:
                    if result["no_chunks"]:
                        upsert_file(conn, result["rel_path"], result["md5"], time.time())
                    elif result["error"]:
                        file_errors.append(FileIndexError(result["rel_path"], result["error"]))

                # Commit after each batch (streaming — progressive results)
                conn.commit()

            # Process files in streaming batches
            batch: list[tuple[int, Path, str, str]] = []
            for i, fpath in enumerate(new_or_modified, start=1):
                rel_path = str(fpath.relative_to(scan_root))
                batch.append((i, fpath, rel_path, crawled_hashes.get(rel_path, "")))
                if len(batch) >= batch_size:
                    process_batch(batch)
                    batch = []

            # Process remaining files
            if batch:
                process_batch(batch)

        # Record which embedding model produced this index so a later model
        # switch triggers a clean rebuild instead of mixing incompatible vectors.
        if detected_dim.get("dim"):
            write_stamp(root, config["embed_model"], detected_dim["dim"])
    finally:
        conn.close()

    return UpdateIndexResult(
        indexed_files=indexed_files,
        deleted_files=len(deleted),
        unchanged_files=len(unchanged),
        chunks_indexed=chunks_indexed,
        file_errors=tuple(file_errors),
    )
