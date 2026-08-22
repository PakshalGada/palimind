from __future__ import annotations

import time
from pathlib import Path

from core.config import load_config, palimind_dir, write_default_config
from core.exceptions import (
    CaptionError,
    EmbeddingError,
    IndexExistsError,
    IndexNotFoundError,
    OCRError,
    ParseError,
)
from core.ingestion.rich_chunker import (
    DocumentMeta,
    RichChunk,
    extract_doc_type,
    extract_doc_year,
    extract_entity_name,
    rich_chunk_caption,
    rich_chunk_document,
)
from core.ingestion.crawler import compute_md5, crawl_directory
from core.ingestion.doc_parser import parse_document
from core.ingestion.image_parser import caption_image
from core.models import (
    ChunkInfo,
    FileIndexError,
    InitIndexResult,
    ProgressCallback,
    UpdateIndexResult,
)
from core.embedder import generate_embeddings_batch
from core.storage.db import (
    delete_file,
    get_connection,
    init_db,
    insert_chunks,
    insert_financial_facts,
    insert_timeline_events,
    upsert_file,
    upsert_file_summary,
)
from core.storage.vector_store import VectorStore
from core.generative.summariser import summarise_file


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
        caption = caption_image(
            file_path, config["ollama_base_url"], config["vision_model"]
        )
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

    from core.ingestion.video_parser import parse_video

    logger = logging.getLogger(__name__)
    rel_path = str(file_path.relative_to(root))
    try:
        chunks_raw, _segments = parse_video(
            file_path,
            whisper_model=config.get("video_whisper_model", "base"),
            chunk_chars=config.get("chunk_size", 800),
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
# Financial fact & timeline extraction (best-effort via LLM)
# ---------------------------------------------------------------------------

def _extract_financial_facts_from_text(
    text: str,
    doc_year: int | None,
    ollama_url: str,
    chat_model: str,
) -> list[dict]:
    """
    Ask the LLM to extract key financial metrics as structured JSON.
    Returns a list of fact dicts or empty list on any failure.
    """
    import json
    import httpx

    if not text or not text.strip():
        return []

    excerpt = text[:6000]
    prompt = f"""Extract financial metrics from the following text.
Return ONLY a JSON array, no explanation. Each item should have:
{{"metric_name": str, "value": float_or_null, "unit": str, "period": str}}

Common metrics: revenue, gross_margin, net_income, operating_income, eps, cash_flow, total_assets, total_debt

Text:
{excerpt}

JSON array:"""

    try:
        resp = httpx.post(
            f"{ollama_url.rstrip('/')}/api/chat",
            json={
                "model": chat_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.0},
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "")

        # Extract JSON array from response
        m = __import__("re").search(r"\[.*\]", content, __import__("re").DOTALL)
        if not m:
            return []

        facts = json.loads(m.group(0))
        if not isinstance(facts, list):
            return []

        result = []
        for fact in facts:
            if not isinstance(fact, dict) or "metric_name" not in fact:
                continue
            result.append({
                "metric_name": str(fact.get("metric_name", "")).lower().replace(" ", "_"),
                "value": float(fact["value"]) if fact.get("value") is not None else None,
                "unit": str(fact.get("unit", "USD")),
                "period": str(fact.get("period", "")),
                "doc_year": doc_year,
            })
        return result
    except Exception:
        return []


def _extract_timeline_events_from_text(
    text: str,
    doc_year: int | None,
    ollama_url: str,
    chat_model: str,
) -> list[dict]:
    """
    Ask the LLM to extract dated events as structured JSON.
    Returns a list of event dicts or empty list on any failure.
    """
    import json
    import httpx

    if not text or not text.strip():
        return []

    excerpt = text[:6000]
    prompt = f"""Extract dated events or announcements from the following text.
Return ONLY a JSON array, no explanation. Each item should have:
{{"event_date": "YYYY-MM-DD or YYYY", "event_year": int_or_null, "event_text": str, "event_type": str}}

event_type options: product_launch, regulatory, financial, leadership, strategic, legal, general

Text:
{excerpt}

JSON array:"""

    try:
        resp = httpx.post(
            f"{ollama_url.rstrip('/')}/api/chat",
            json={
                "model": chat_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.0},
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "")

        m = __import__("re").search(r"\[.*\]", content, __import__("re").DOTALL)
        if not m:
            return []

        events = json.loads(m.group(0))
        if not isinstance(events, list):
            return []

        result = []
        for event in events:
            if not isinstance(event, dict) or "event_text" not in event:
                continue
            result.append({
                "event_date": str(event.get("event_date", "")),
                "event_year": int(event["event_year"]) if event.get("event_year") else doc_year,
                "event_text": str(event["event_text"]),
                "event_type": str(event.get("event_type", "general")),
            })
        return result
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Main index update
# ---------------------------------------------------------------------------

def update_index(
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
    new_or_modified, unchanged, deleted = crawl_directory(root)
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
            for i, fpath in enumerate(new_or_modified, start=1):
                rel_path = str(fpath.relative_to(root))
                report("index", current=i, total=len(new_or_modified), message=rel_path)

                md5 = compute_md5(fpath)
                if not md5:
                    file_errors.append(
                        FileIndexError(rel_path, "Could not compute file hash")
                    )
                    continue

                vstore.delete_file(rel_path)

                try:
                    rich_chunks = extract_chunks(fpath, root, config)
                except (ParseError, CaptionError, OCRError) as e:
                    file_errors.append(FileIndexError(rel_path, str(e)))
                    continue

                if not rich_chunks:
                    # Upsert file record even if no chunks (so crawl knows it's indexed)
                    upsert_file(conn, rel_path, md5, time.time())
                    continue

                # Extract metadata from the first rich chunk (they all share doc meta)
                first = rich_chunks[0]
                file_id = upsert_file(
                    conn,
                    rel_path,
                    md5,
                    time.time(),
                    doc_year=first.doc_year,
                    doc_type=first.doc_type,
                    entity_name=first.entity_name,
                )

                texts = [c.content for c in rich_chunks]
                try:
                    embeddings = generate_embeddings_batch(
                        texts, config["ollama_base_url"], config["embed_model"]
                    )
                except EmbeddingError as e:
                    file_errors.append(FileIndexError(rel_path, str(e)))
                    continue

                # Build DB chunk rows with full metadata
                db_chunks = []
                valid_infos: list[tuple[int, RichChunk, list[float]]] = []
                for idx, (chunk, emb) in enumerate(zip(rich_chunks, embeddings)):
                    if not emb:
                        continue
                    db_chunks.append((
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
                    ))
                    valid_infos.append((idx, chunk, emb))

                if valid_infos:
                    chunk_db_ids = insert_chunks(conn, file_id, db_chunks)

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
                        for j, (_, chunk, emb) in enumerate(valid_infos)
                    ]
                    vstore.insert(vector_data)
                    chunks_indexed += len(vector_data)
                    indexed_files += 1

                    # ── File summary ────────────────────────────────────────
                    if config.get("summarise", True):
                        report(
                            "summarise",
                            current=i,
                            total=len(new_or_modified),
                            message=rel_path,
                        )
                        full_text = "\n\n".join(texts)
                        summary = summarise_file(
                            full_text,
                            config["ollama_base_url"],
                            config["chat_model"],
                            max_chars=config.get("summary_max_chars", 8000),
                        )
                        if summary:
                            upsert_file_summary(conn, rel_path, summary)

                    # ── Financial fact extraction (financial docs only) ─────
                    doc_type = first.doc_type
                    if doc_type in ("10-K", "10-Q", "annual_report") and config.get(
                        "extract_financials", True
                    ):
                        report("extract_financials", current=i, total=len(new_or_modified), message=rel_path)
                        full_text = "\n\n".join(texts[:20])  # first 20 chunks
                        facts = _extract_financial_facts_from_text(
                            full_text, first.doc_year,
                            config["ollama_base_url"], config["chat_model"]
                        )
                        if facts:
                            insert_financial_facts(conn, file_id, facts)

                    # ── Timeline event extraction ─────────────────────────
                    if config.get("extract_timeline", True):
                        report("extract_timeline", current=i, total=len(new_or_modified), message=rel_path)
                        full_text = "\n\n".join(texts[:15])
                        events = _extract_timeline_events_from_text(
                            full_text, first.doc_year,
                            config["ollama_base_url"], config["chat_model"]
                        )
                        if events:
                            insert_timeline_events(conn, file_id, events)

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
