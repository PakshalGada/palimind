import time
from pathlib import Path
from typing import Optional

import typer

from ..config import db_path, load_config, palimind_dir, write_default_config
from ..index.chunker import chunk_text
from ..index.walker import walk
from ..retrieval.embedder import embed_batch
from .common import file_hash, open_store


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

    store = open_store(root)
    t0 = time.perf_counter()

    total_files = 0
    total_chunks = 0

    for entry in walk(root, allowed_extensions=extensions):
        rel = str(entry.relative)
        abs_path = entry.absolute
        fhash = file_hash(abs_path)

        if store.is_file_indexed(rel, fhash):
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
                file_hash=fhash,
                embedding=vec,
            )

        store.commit()
        store.mark_file_indexed(rel, fhash)

        total_files += 1
        total_chunks += len(chunks)

    elapsed = time.perf_counter() - t0
    store.close()

    typer.echo(
        f"\nDone. {total_files} files indexed, "
        f"{total_chunks} chunks stored, "
        f"{elapsed:.1f}s elapsed."
    )
