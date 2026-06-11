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

# Register email sub-app
from core.email.cli import app as email_app  # noqa: E402

app.add_typer(email_app, name="email")


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
    """Start an interactive agent chat session."""
    target_dir = path.resolve()
    try:
        require_index(target_dir)
    except IndexNotFoundError as e:
        print_error(str(e))
        raise typer.Exit(1)

    from core.config import load_config
    config = load_config(target_dir)
    ollama_url = config.get("ollama_base_url", "https://heavy-hounds-hunt.loca.lt")
    chat_model = config.get("chat_model", "gemma4:e4b")

    from core.agent import needs_retrieval, reformulate_query

    print_header("Interactive Agent Chat")
    print_info("Type 'exit' or 'quit' to end the session.")

    history = []

    while True:
        try:
            user_input = input("\nYou> ")
            if user_input.lower() in ["exit", "quit"]:
                break
            if not user_input.strip():
                continue

            standalone_query = reformulate_query(user_input, history, ollama_url, chat_model)
            
            if needs_retrieval(standalone_query, history, ollama_url, chat_model):
                if standalone_query != user_input:
                    print_info(f"Searching knowledge base for: {standalone_query}")
                try:
                    context, stream = query_stream(target_dir, standalone_query, history=history)
                    if context.sources:
                        print_info(f"Sources: {', '.join(context.sources)}")
                except PalimindError as e:
                    print_error(str(e))
                    continue
            else:
                from core.generative.responder import generate_response_stream
                stream = generate_response_stream(
                    query=user_input, 
                    context="",
                    image_paths=[],
                    ollama_url=ollama_url,
                    chat_model=chat_model,
                    system_prompt="You are a helpful assistant.",
                    history=history,
                    is_chat_only=True
                )

            console.print("[bold magenta]Palimind:[/bold magenta] ", end="")
            answer_chunks = []
            try:
                for token in stream:
                    console.print(token, end="")
                    answer_chunks.append(token)
            except PalimindError as e:
                console.print()
                print_error(str(e))
                continue
            console.print()

            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": "".join(answer_chunks)})

            if len(history) > 10:
                history = history[-10:]

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


@app.command()
def hotkey(
    action: str = typer.Argument(
        "start",
        help="Action: 'start' to begin listening, 'stop' to stop, 'trigger' to run manually (for Wayland)"
    ),
    hotkey_combo: str = typer.Option(
        "ctrl+shift+e",
        "--hotkey",
        "-k",
        help="Hotkey combination (e.g., 'ctrl+shift+e')"
    ),
    api_url: str = typer.Option(
        "http://localhost:8000",
        "--api-url",
        help="FastAPI server URL"
    ),
):
    """
    Global hotkey listener for capturing text and saving to Fields.
    
    Usage:
        pm hotkey start                    # Start listening
        pm hotkey start --hotkey alt+shift+c  # Custom hotkey
        pm hotkey trigger                  # Trigger the capture manually (for Wayland/Hyprland)
        pm hotkey stop                     # Stop listening
    """
    try:
        from hotkey.manager import HotkeyManager, HotkeyConfig
    except ImportError:
        print_error("Hotkey feature requires extra dependencies.")
        print_info("Install with: pip install -e '.[hotkey]'")
        raise typer.Exit(1)
    
    action = action.lower().strip()
    
    if action == "start":
        print_header("Palimind Hotkey Listener")
        print_info(f"Hotkey: {hotkey_combo}")
        print_info(f"API Server: {api_url}")
        print_info("Listening for hotkey... (Press Ctrl+C to stop)")
        print()
        
        try:
            config = HotkeyConfig(
                hotkey_combo=hotkey_combo,
                api_base_url=api_url,
            )
            manager = HotkeyManager(config)
            
            def on_event(event):
                """Callback when capture is complete."""
                print_success(
                    f"Captured to '{event.selected_field.name}': "
                    f"{len(event.selected_text)} chars"
                )
            
            manager.start(on_event)
            
            # Keep running until interrupted
            import time
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n")
                manager.stop()
                print_success("Hotkey listener stopped")
                
        except ImportError as e:
            print_error(f"Missing dependency: {e}")
            print_info("Install with: pip install -e '.[hotkey]'")
            raise typer.Exit(1)
        except Exception as e:
            print_error(f"Error starting hotkey listener: {e}")
            raise typer.Exit(1)
            
    elif action == "trigger":
        print_header("Triggering Palimind Capture (Wayland Mode)")
        try:
            config = HotkeyConfig(api_base_url=api_url)
            manager = HotkeyManager(config)
            
            # Use a mutable list or similar to track completion
            status = {"done": False}
            
            def on_event(event):
                print_success(
                    f"Captured to '{event.selected_field.name}': "
                    f"{len(event.selected_text)} chars"
                )
                status["done"] = True
                
            manager.event_callback = on_event
            manager._on_hotkey_pressed(sync=True)
            
            # Keep alive until flow finishes
            import time
            for _ in range(600):  # Wait up to 60 seconds
                if status["done"]:
                    break
                time.sleep(0.1)
                
        except Exception as e:
            print_error(f"Error triggering hotkey: {e}")
            raise typer.Exit(1)
    
    elif action == "stop":
        print_info("Stopping hotkey listener...")
        print_info("(Make sure the listener is running in another terminal)")
        print_info("Stopping can only be done by terminating the listener process (Ctrl+C)")
        
    else:
        print_error(f"Unknown action: {action}")
        print_info("Use 'start', 'stop', or 'trigger'")
        raise typer.Exit(1)
