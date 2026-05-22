import time
from pathlib import Path
from typing import Optional

import typer

from ..config import load_config
from ..index.chunker import chunk_text
from ..index.walker import walk
from ..retrieval.embedder import embed_batch
from .common import file_hash, open_store, require_index


def add(
    path: Optional[str] = typer.Argument(None, help="Indexed folder (default: cwd)"),
    prune: bool = typer.Option(
        True, "--prune/--no-prune", help="Remove chunks for deleted files"
    ),
) -> None:
    """Re-index new or changed files. Skips anything already up to date."""
    root = Path(path).resolve() if path else Path.cwd()
    require_index(root)

    cfg = load_config(root)
    extensions = set(cfg["extensions"])
    chunk_size: int = cfg["chunk_size"]
    chunk_overlap: int = cfg["chunk_overlap"]
    embed_model: str = cfg["embed_model"]

    store = open_store(root)
    t0 = time.perf_counter()

    added_files = 0
    total_chunks = 0

    seen_rel_paths: set[str] = set()

    for entry in walk(root, allowed_extensions=extensions):
        rel = str(entry.relative)
        abs_path = entry.absolute
        fhash = file_hash(abs_path)
        seen_rel_paths.add(rel)

        if store.is_file_indexed(rel, fhash):
            continue

        store.delete_chunks_for_file(rel)

        try:
            text = abs_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            typer.echo(f"  [skip] {rel} (unreadable)")
            continue

        chunks = chunk_text(text, rel, chunk_size, chunk_overlap)
        if not chunks:
            continue

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

        typer.echo(f"  [index] {rel} — {len(chunks)} chunks")
        added_files += 1
        total_chunks += len(chunks)

    if prune:
        indexed_paths = store.all_indexed_paths()
        removed = 0
        for old_path in indexed_paths:
            if old_path not in seen_rel_paths:
                store.delete_chunks_for_file(old_path)
                typer.echo(f"  [prune] {old_path} (deleted from disk)")
                removed += 1
        if removed:
            typer.echo(f"Pruned {removed} deleted file(s).")

    elapsed = time.perf_counter() - t0
    store.close()

    if added_files == 0:
        typer.echo("Nothing to update — index is already current.")
    else:
        typer.echo(
            f"\nDone. {added_files} file(s) indexed/updated, "
            f"{total_chunks} chunks stored, "
            f"{elapsed:.1f}s elapsed."
        )
