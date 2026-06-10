from __future__ import annotations

from pathlib import Path

import typer

from core.api import (
    IndexExistsError,
    IndexNotFoundError,
    NoContextError,
    PalimindError,
    initialize_index,
    query_stream,
    require_index,
    update_index,
)
from core.api_server import run_server
from core.cli.ui import (
    console,
    create_progress,
    print_error,
    print_header,
    print_info,
    print_success,
)

app = typer.Typer(help="Palimind - Local Multimodal RAG CLI")


@app.command()
def init(path: Path = typer.Argument(..., help="Path to initialize indexing")):
    """Initialize a new index in the specified directory."""
    target_dir = path.resolve()
    if not target_dir.is_dir():
        print_error(f"Directory {target_dir} does not exist.")
        raise typer.Exit(1)

    print_header("Initializing Palimind Index")
    try:
        result = initialize_index(target_dir)
    except IndexExistsError as e:
        print_info(str(e) + " Use 'pm add' to update.")
        raise typer.Exit(0)
    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)

    print_success(f"Initialized empty index at {result.index_dir}")
    print_info("Run 'pm add .' to start indexing files.")


@app.command()
def add(path: Path = typer.Argument(Path("."), help="Path to the indexed directory")):
    """Update an existing index with new or modified files."""
    target_dir = path.resolve()
    print_header("Updating Index")

    progress_state: dict = {}

    def on_progress(phase, *, current=0, total=None, message=""):
        if phase == "crawl" and message and "task" not in progress_state:
            progress_state["task"] = progress.add_task(f"[cyan]{message}", total=None)
        elif phase == "delete" and total:
            if "del_task" not in progress_state:
                progress_state["del_task"] = progress.add_task(
                    "[red]Removing deleted files...", total=total
                )
            progress.advance(progress_state["del_task"])
        elif phase == "index" and total:
            if "idx_task" not in progress_state:
                progress_state["idx_task"] = progress.add_task(
                    "[green]Indexing files...", total=total
                )
            progress.advance(progress_state["idx_task"])
        elif phase == "summarise" and total:
            if "sum_task" not in progress_state:
                progress_state["sum_task"] = progress.add_task(
                    "[yellow]Summarising files...", total=total
                )
            progress.update(progress_state["sum_task"], completed=current)

    try:
        with create_progress() as progress:
            progress_state["progress"] = progress
            result = update_index(target_dir, on_progress=on_progress)
    except IndexNotFoundError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except PalimindError as e:
        print_error(str(e))
        raise typer.Exit(1)

    print_success(
        f"Index updated: {result.indexed_files} file(s), "
        f"{result.chunks_indexed} chunk(s), "
        f"{result.deleted_files} removed, "
        f"{result.unchanged_files} unchanged."
    )
    for err in result.file_errors:
        print_error(f"{err.path}: {err.error}")


@app.command()
def ask(
    query: str = typer.Argument(..., help="Question to ask"),
    path: Path = typer.Option(Path("."), "--path", "-p", help="Path to the indexed directory"),
):
    """Ask a question against the indexed knowledge base."""
    target_dir = path.resolve()
    print_header("Answering Question")
    print_info(f"Retrieving context for: {query}")

    try:
        context, stream = query_stream(target_dir, query)
    except IndexNotFoundError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except NoContextError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except PalimindError as e:
        print_error(str(e))
        raise typer.Exit(1)

    if context.sources:
        print_info(f"Sources: {', '.join(context.sources)}")

    print_info("Generating response...")
    console.print("[bold magenta]Palimind:[/bold magenta] ", end="")
    try:
        for token in stream:
            console.print(token, end="")
    except PalimindError as e:
        console.print()
        print_error(str(e))
        raise typer.Exit(1)
    console.print()


@app.command()
def chat(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Path to the indexed directory"),
):
    """Start an interactive chat session."""
    target_dir = path.resolve()
    try:
        require_index(target_dir)
    except IndexNotFoundError as e:
        print_error(str(e))
        raise typer.Exit(1)

    print_header("Interactive Chat")
    print_info("Type 'exit' or 'quit' to end the session.")

    while True:
        try:
            user_input = input("\nYou> ")
            if user_input.lower() in ["exit", "quit"]:
                break
            if not user_input.strip():
                continue
            ask(query=user_input, path=target_dir)
        except (KeyboardInterrupt, EOFError):
            break

@app.command()
def ui(port: int = typer.Option(8000, "--port", help="Port to run the UI server on")):
    """Start the Palimind V2 Boardroom UI."""
    import webbrowser
    import threading
    import time
    
    print_header("Palimind V2 Boardroom")
    print_info(f"Starting server on http://localhost:{port}/ui/")
    
    def open_browser():
        time.sleep(1.5)
        webbrowser.open(f"http://localhost:{port}/ui/")
        
    threading.Thread(target=open_browser, daemon=True).start()
    run_server(port)
