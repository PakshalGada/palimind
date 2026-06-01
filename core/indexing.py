import time
from pathlib import Path

from core.config import load_config, palimind_dir, write_default_config
from core.exceptions import (
    CaptionError,
    EmbeddingError,
    IndexExistsError,
    IndexNotFoundError,
    ParseError,
)
from core.ingestion.chunker import chunk_text
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
from core.retrieval.embedder import generate_embeddings_batch
from core.storage.db import (
    delete_file,
    get_connection,
    init_db,
    insert_chunks,
    upsert_file,
)
from core.storage.vector_store import delete_vectors_for_file, insert_vectors


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


def extract_chunks(file_path: Path, root: Path, config: dict) -> list[ChunkInfo]:
    ext = file_path.suffix.lower()

    if ext in config["image_extensions"]:
        caption = caption_image(
            file_path, config["ollama_base_url"], config["vision_model"]
        )
        if caption:
            return [ChunkInfo(content=caption, chunk_type="caption")]
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

    chunks = chunk_text(text, config["chunk_size"], config["chunk_overlap"])
    return [ChunkInfo(content=c, chunk_type="text") for c in chunks]


def update_index(
    root: Path,
    *,
    on_progress: ProgressCallback | None = None,
) -> UpdateIndexResult:
    root = require_index(root)
    config = load_config(root)
    init_db(root)

    def report(phase: str, *, current: int = 0, total: int | None = None, message: str = ""):
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

    if deleted:
        for i, rel_path in enumerate(deleted, start=1):
            delete_vectors_for_file(root, rel_path)
            delete_file(conn, rel_path)
            report("delete", current=i, total=len(deleted), message=rel_path)

    indexed_files = 0
    if new_or_modified:
        for i, fpath in enumerate(new_or_modified, start=1):
            rel_path = str(fpath.relative_to(root))
            report("index", current=i, total=len(new_or_modified), message=rel_path)

            md5 = compute_md5(fpath)
            if not md5:
                file_errors.append(
                    FileIndexError(rel_path, "Could not compute file hash")
                )
                continue

            delete_vectors_for_file(root, rel_path)
            file_id = upsert_file(conn, rel_path, md5, time.time())

            try:
                chunks_info = extract_chunks(fpath, root, config)
            except (ParseError, CaptionError) as e:
                file_errors.append(FileIndexError(rel_path, str(e)))
                continue

            if not chunks_info:
                continue

            texts = [c.content for c in chunks_info]
            try:
                embeddings = generate_embeddings_batch(
                    texts, config["ollama_base_url"], config["embed_model"]
                )
            except EmbeddingError as e:
                file_errors.append(FileIndexError(rel_path, str(e)))
                continue

            vector_data = []
            db_chunks = []
            for idx, (info, emb) in enumerate(zip(chunks_info, embeddings)):
                if not emb:
                    continue
                db_chunks.append((idx, info.chunk_type, info.content))
                vector_data.append(
                    {
                        "vector": emb,
                        "file_path": rel_path,
                        "chunk_index": idx,
                        "chunk_type": info.chunk_type,
                        "content": info.content,
                    }
                )

            if vector_data:
                insert_vectors(root, vector_data)
                insert_chunks(conn, file_id, db_chunks)
                chunks_indexed += len(vector_data)
                indexed_files += 1

    conn.close()

    return UpdateIndexResult(
        indexed_files=indexed_files,
        deleted_files=len(deleted),
        unchanged_files=len(unchanged),
        chunks_indexed=chunks_indexed,
        file_errors=tuple(file_errors),
    )
