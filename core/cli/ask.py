from pathlib import Path
from typing import Optional

import typer

from ..config import load_config
from ..generative.responder import respond
from ..retrieval.embedder import embed_one
from ..retrieval.searcher import search
from .common import open_store, require_index


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
    require_index(root)

    cfg = load_config(root)
    embed_model: str = cfg["embed_model"]
    chat_model: str = cfg["chat_model"]

    store = open_store(root)

    try:
        query_vec = embed_one(question, model=embed_model)
    except RuntimeError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)

    hits = search(query_vec, store, k=k)

    if not hits:
        typer.echo("The index is empty. Run `pm init` to index some files.")
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
