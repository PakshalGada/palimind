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
    create_spinner,
    print_chat_ai_prefix,
    print_chat_user_prefix,
    print_error,
    print_footer,
    print_header,
    print_info,
    print_sources,
    print_startup_banner,
    print_success,
    print_summary_table,
)

app = typer.Typer(help="Palimind - Local Multimodal RAG CLI")

# Register email sub-app
from core.email.cli import app as email_app  # noqa: E402

app.add_typer(email_app, name="email")

config_app = typer.Typer(help="Manage PaliMind configuration")
app.add_typer(config_app, name="config")

@config_app.command("theme")
def set_theme(
    name: str = typer.Argument(..., help="Theme name: teal, purple, amber, blue, coral"),
    path: Path = typer.Option(Path("."), "--path", "-p")
):
    """Set the accent color theme for the CLI."""
    from core.config import load_config, save_config
    from core.cli.ui import THEMES, print_error, print_success, console
    
    if name not in THEMES:
        print_error(f"Unknown theme: \"{name}\"\n")
        console.print("  Available themes:")
        console.print("    teal    — default, clean technical")
        console.print("    purple  — hacker-core")
        console.print("    amber   — retro terminal")
        console.print("    blue    — calm, professional")
        console.print("    coral   — bold, energetic")
        raise typer.Exit(1)
        
    target_dir = path.resolve()
    config = load_config(target_dir)
    config["theme"] = name
    save_config(target_dir, config)
    
    print_success(f'Theme set to "{name}"\n')
    color = THEMES[name]["rich"]
    console.print(f"  [bold {color}]◆ Palimind[/bold {color}]\n")


@app.command()
def init(path: Path = typer.Argument(..., help="Path to initialize indexing")):
    """Initialize a new index in the specified directory."""
    target_dir = path.resolve()
    from core.config import load_config
    config = load_config(target_dir)
    if not target_dir.is_dir():
        print_error(f"Directory {target_dir} does not exist.")
        raise typer.Exit(1)

    print_header("Initializing Palimind Index", config)
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
    from core.config import load_config
    config = load_config(target_dir)
    print_header("Updating Index", config)

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
    except IndexNotFoundError:
        print_error(f"No index found in [cyan]{target_dir}[/cyan]")
        print_info("Run [bold]pm init[/bold] first to create one.")
        raise typer.Exit(1)
    except PalimindError as e:
        print_error(str(e))
        raise typer.Exit(1)

    print_success("Index Complete")
    print_summary_table([
        ("Files Indexed", str(result.indexed_files)),
        ("Chunks Created", str(result.chunks_indexed)),
        ("Deleted", str(result.deleted_files)),
        ("Unchanged", str(result.unchanged_files)),
    ])
    for err in result.file_errors:
        print_error(f"{err.path}: {err.error}")


@app.command()
def ask(
    query: str = typer.Argument(..., help="Question to ask"),
    path: Path = typer.Option(Path("."), "--path", "-p", help="Path to the indexed directory"),
):
    """Ask a question against the indexed knowledge base."""
    target_dir = path.resolve()
    from core.config import load_config
    config = load_config(target_dir)
    print_header("Answering Question", config)
    
    try:
        with create_spinner() as spinner:
            spinner.add_task("Searching knowledge base...", total=None)
            context, stream = query_stream(target_dir, query)
    except IndexNotFoundError:
        print_error(f"No index found in [cyan]{target_dir}[/cyan]")
        print_info("Run [bold]pm init[/bold] first to create one.")
        raise typer.Exit(1)
    except NoContextError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except PalimindError as e:
        print_error(str(e))
        raise typer.Exit(1)

    if context.sources:
        print_sources(context.sources, config)

    print_chat_ai_prefix(config)
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
    except IndexNotFoundError:
        print_error(f"No index found in [cyan]{target_dir}[/cyan]")
        print_info("Run [bold]pm init[/bold] first to create one.")
        raise typer.Exit(1)

    from core.config import load_config
    config = load_config(target_dir)
    ollama_url = config.get("ollama_base_url", "http://localhost:11434")
    chat_model = config.get("chat_model", "gemma4:e2b")

    from core.agent import needs_retrieval, reformulate_query

    print_startup_banner(config)
    print_header("Interactive Agent Chat", config)
    print_info("Type 'exit' or 'quit' to end the session.")

    history = []

    while True:
        try:
            print_chat_user_prefix()
            user_input = input()
            if user_input.lower() in ["exit", "quit"]:
                break
            if not user_input.strip():
                continue

            standalone_query = reformulate_query(user_input, history, ollama_url, chat_model)
            
            if needs_retrieval(standalone_query, history, ollama_url, chat_model):
                try:
                    with create_spinner() as spinner:
                        spinner.add_task("Searching knowledge base...", total=None)
                        context, stream = query_stream(target_dir, standalone_query, history=history)
                    if context.sources:
                        print_sources(context.sources, config)
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

            print_chat_ai_prefix(config)
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

    print_footer("Session ended.", config)

@app.command()
def ui(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Workspace path")
):
    """Start the Palimind V2 Boardroom UI via Electron."""
    import subprocess
    import sys
    import os
    from pathlib import Path
    
    target_dir = path.resolve()
    from core.config import load_config
    config = load_config(target_dir)
    
    print_startup_banner(config)
    print_header("Palimind V2 Boardroom", config)
    
    root_dir = Path(__file__).parent.parent.parent
    
    # Start Electron using platform-specific npm script
    # Linux requires --no-sandbox due to SUID sandbox restrictions (start-linux)
    with create_spinner() as spinner:
        spinner.add_task("Starting Electron...", total=None)
        try:
            if os.name == 'nt':
                subprocess.run(["npm.cmd", "run", "start-windows"], cwd=root_dir)
            else:
                subprocess.run(["npm", "run", "start-linux"], cwd=root_dir)
        except KeyboardInterrupt:
            print_info("Electron wrapper stopped.")
        except Exception as e:
            print_error(f"Failed to start Electron: {e}")


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
    path: Path = typer.Option(Path("."), "--path", "-p", help="Workspace path")
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
        print_info("Install with: pip install -e '.\\[hotkey]'")
        raise typer.Exit(1)
    
    action = action.lower().strip()
    
    target_dir = path.resolve()
    from core.config import load_config
    config = load_config(target_dir)
    
    if action == "start":
        print_startup_banner(config)
        print_header("Palimind Hotkey Listener", config)
        print_info(f"Hotkey: {hotkey_combo}")
        print_info(f"API Server: {api_url}")
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
            with create_spinner() as spinner:
                spinner.add_task("Listening for hotkey... Ctrl+C to stop", total=None)
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
            print_info("Install with: pip install -e '.\\[hotkey]'")
            raise typer.Exit(1)
        except Exception as e:
            print_error(f"Error starting hotkey listener: {e}")
            raise typer.Exit(1)
            
    elif action == "trigger":
        print_startup_banner(config)
        print_header("Triggering Palimind Capture (Wayland Mode)", config)
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
            with create_spinner() as spinner:
                spinner.add_task("Waiting for capture to complete...", total=None)
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

@app.command()
def swarm(
    query: str = typer.Argument(..., help="Query for the swarm orchestrator"),
    path: Path = typer.Option(Path("."), "--path", "-p", help="Workspace path")
):
    """Run a query through the Agent Swarm."""
    target_dir = path.resolve()
    from core.config import load_config
    config = load_config(target_dir)
    ollama_url = config.get("ollama_base_url", "http://localhost:11434")
    chat_model = config.get("chat_model", "gemma4:e4b")
    
    print_startup_banner(config)
    print_header("Agent Swarm", config)
    from core.swarm.orchestrator import SwarmOrchestrator
    orchestrator = SwarmOrchestrator(target_dir, ollama_url, chat_model)
    
    print_info(f"Query: {query}")
    
    with create_spinner() as spinner:
        spinner.add_task("Swarm is thinking...", total=None)
        response = orchestrator.run_swarm(query)
    
    console.print("[bold magenta]Swarm:[/bold magenta] ", end="")
    console.print(response)

@app.command()
def document(
    file_path: str = typer.Argument(..., help="Path to the document to analyze"),
    query: str = typer.Argument(..., help="What to do with the document"),
    path: Path = typer.Option(Path("."), "--path", "-p", help="Workspace path")
):
    """Run Document Mode on a specific file."""
    target_dir = path.resolve()
    from core.config import load_config
    config = load_config(target_dir)
    ollama_url = config.get("ollama_base_url", "http://localhost:11434")
    chat_model = config.get("chat_model", "gemma4:e4b")
    
    print_startup_banner(config)
    print_header(f"Document Mode: {file_path}", config)
    from core.swarm.orchestrator import SwarmOrchestrator
    orchestrator = SwarmOrchestrator(target_dir, ollama_url, chat_model)
    
    with create_spinner() as spinner:
        spinner.add_task("Analyzing document...", total=None)
        response = orchestrator.run_document_mode(file_path, query)
    
    console.print("[bold magenta]DocumentAgent:[/bold magenta] ", end="")
    console.print(response)

