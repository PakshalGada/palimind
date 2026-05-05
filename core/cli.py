import hashlib
import time
from pathlib import Path
from typing import Optional

import typer

from .chunker import chunk_text
from .config import (
    db_path,
    load_config,
    palimind_dir,
    write_default_config,
)
from .embedder import embed_batch, embed_one
from .responder import respond
from .searcher import search
from .store import Store
from .walker import DEFAULT_EXTENSIONS, _extract_text, walk

app = typer.Typer(add_completion=False, help="palimind — local RAG")


def _file_hash(path: Path) -> str:
    """MD5 hash of file contents — fast enough for change detection."""
    h = hashlib.md5(path.read_bytes()).hexdigest()
    return h


def _require_index(root: Path) -> None:
    if not db_path(root).exists():
        typer.echo("No index found. Run `palimind init` first.")
        raise typer.Exit(code=1)


def _open_store(root: Path) -> Store:
    return Store(db_path(root))


@app.command()
def init(
    path: Optional[str] = typer.Argument(None, help="Folder to index (default: cwd)"),
) -> None:
    """Index a folder so you can ask questions about it."""
    root = Path(path).resolve() if path else Path.cwd()

    if not root.is_dir():
        typer.echo(f"Error: '{root}' is not a directory.")
        raise typer.Exit(code=1)

    pdir = palimind_dir(root)
    dbp = db_path(root)

    if dbp.exists():
        typer.echo(
            f"Index already exists at {pdir}.\n"
            "Run `palimind add` to update it with new or changed files."
        )
        raise typer.Exit(code=0)

    pdir.mkdir(exist_ok=True)
    write_default_config(root)
    cfg = load_config(root)

    extensions = set(cfg["extensions"])
    chunk_size: int = cfg["chunk_size"]
    chunk_overlap: int = cfg["chunk_overlap"]
    embed_model: str = cfg["embed_model"]

    store = _open_store(root)
    t0 = time.perf_counter()

    total_files = 0
    total_chunks = 0

    for entry in walk(root, allowed_extensions=extensions):
        rel = str(entry.relative)
        abs_path = entry.absolute
        file_hash = _file_hash(abs_path)

        if store.is_file_indexed(rel, file_hash):
            typer.echo(f"  [skip] {rel} (unchanged)")
            continue

        try:
            text = abs_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            typer.echo(f"  [skip] {rel} (unreadable)")
            continue

        chunks = chunk_text(text, rel, chunk_size, chunk_overlap)
        if not chunks:
            continue

        typer.echo(f"  [index] {rel} — {len(chunks)} chunks")

        try:
            vectors = embed_batch([c.text for c in chunks], model=embed_model)
        except RuntimeError as e:
            typer.echo(f"Error: {e}")
            raise typer.Exit(code=1)

        for chunk, vec in zip(chunks, vectors):
            store.insert_chunk(
                chunk_text=chunk.text,
                source_path=chunk.source_path,
                start_char=chunk.start_char,
                end_char=chunk.end_char,
                file_hash=file_hash,
                embedding=vec,
            )

        store.commit()
        store.mark_file_indexed(rel, file_hash)

        total_files += 1
        total_chunks += len(chunks)

    elapsed = time.perf_counter() - t0
    store.close()

    typer.echo(
        f"\nDone. {total_files} files indexed, "
        f"{total_chunks} chunks stored, "
        f"{elapsed:.1f}s elapsed."
    )


@app.command()
def ask(
    question: str = typer.Argument(
        ..., help="Question to answer from the indexed files"
    ),
    path: Optional[str] = typer.Option(
        None, "--path", "-p", help="Indexed folder (default: cwd)"
    ),
    k: int = typer.Option(5, "--top", "-k", help="Number of chunks to retrieve"),
) -> None:
    """Ask a question grounded in the indexed files."""
    root = Path(path).resolve() if path else Path.cwd()
    _require_index(root)

    cfg = load_config(root)
    embed_model: str = cfg["embed_model"]
    chat_model: str = cfg["chat_model"]

    store = _open_store(root)

    try:
        query_vec = embed_one(question, model=embed_model)
    except RuntimeError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)

    hits = search(query_vec, store, k=k)

    if not hits:
        typer.echo("The index is empty. Run `palimind init` to index some files.")
        raise typer.Exit(code=0)

    context_chunks: list[tuple[str, str]] = []
    seen_sources: list[str] = []

    for chunk_id, _score in hits:
        row = store.get_chunk(chunk_id)
        if row is None:
            continue
        chunk_text_str, source_path = row
        context_chunks.append((chunk_text_str, source_path))
        if source_path not in seen_sources:
            seen_sources.append(source_path)

    store.close()

    typer.echo(f"\nSources: {', '.join(seen_sources)}\n")

    try:
        respond(question, context_chunks, model=chat_model)
    except RuntimeError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)
