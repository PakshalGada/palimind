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
    print_warning,
)

app = typer.Typer(help="Palimind - Local Multimodal RAG CLI")



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
def ui(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Workspace path"),
    port: int = typer.Option(8000, "--port", help="Backend API port (window loads http://127.0.0.1:<port>/ui)"),
    skip_install: bool = typer.Option(False, "--skip-install", help="Skip dependency install and frontend build"),
    skip_build: bool = typer.Option(False, "--skip-build", help="Skip rebuilding the desktop app"),
    keep_backend: bool = typer.Option(False, "--keep-backend", help="Keep Ollama/API server running after the app closes"),
):
    """One command to launch everything: installs dependencies, runs OpenCode auth,
    starts Ollama, serves the API and opens the Palimind app."""
    import os
    import shutil
    import socket
    import subprocess
    import sys
    import time

    target_dir = path.resolve()
    from core.config import load_config
    config = load_config(target_dir)

    print_startup_banner(config)
    print_header("Palimind Launcher", config)

    root_dir = Path(__file__).parent.parent.parent
    frontend_dir = root_dir / "frontend"
    started_procs: list[subprocess.Popen] = []
    backend_proc: subprocess.Popen | None = None
    ollama_proc: subprocess.Popen | None = None

    def port_up(p: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.25)
            return s.connect_ex(("127.0.0.1", p)) == 0

    def wait_port(p: int, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if port_up(p):
                return True
            time.sleep(0.4)
        return False

    def spawn(cmd: list[str], **kw) -> subprocess.Popen:
        kwargs = {"cwd": str(root_dir), "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if os.name != "nt":
            kwargs["start_new_session"] = True
        kwargs.update(kw)
        return subprocess.Popen(cmd, **kwargs)

    try:
        if not skip_install:
            try:
                import fastapi  # noqa: F401
                import uvicorn  # noqa: F401
                print_success("Python dependencies installed")
            except ImportError:
                print_info("Installing Python dependencies (pip install -e .)...")
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-e", str(root_dir)],
                    cwd=str(root_dir),
                    check=True,
                )

            npm = "npm.cmd" if os.name == "nt" else "npm"
            if not (root_dir / "node_modules").exists():
                print_info("Installing root dependencies (npm install)...")
                subprocess.run([npm, "install"], cwd=str(root_dir), check=True)
            else:
                print_success("Root dependencies installed")

            if not (frontend_dir / "node_modules").exists():
                print_info("Installing frontend dependencies (npm install)...")
                subprocess.run([npm, "install"], cwd=str(frontend_dir), check=True)
            else:
                print_success("Frontend dependencies installed")

            print_info("Building frontend...")
            subprocess.run([npm, "run", "build"], cwd=str(frontend_dir), check=True)
            print_success("Frontend built")
        elif not (frontend_dir / "dist").exists():
            print_error("frontend/dist missing — rerun without --skip-install")
            raise typer.Exit(1)

        opencode_bin = shutil.which("opencode")
        if opencode_bin is None:
            print_warning("OpenCode not found on PATH — skipping auth step")
        else:
            from core.opencode_auth import get_key
            if get_key() is None:
                print_warning("OpenCode not authenticated — opening auth login...")
                subprocess.run([opencode_bin, "auth", "login"])
                print_success("OpenCode authenticated")
            else:
                print_success("OpenCode already authenticated")

        if not port_up(11434):
            ollama_bin = shutil.which("ollama")
            if ollama_bin:
                print_info("Starting Ollama server...")
                ollama_proc = spawn([ollama_bin, "serve"])
                if wait_port(11434, 20):
                    print_success("Ollama running on :11434")
                else:
                    print_warning("Ollama did not respond on :11434 yet — continuing")
            else:
                print_warning("Ollama not found on PATH — skipping (local models unavailable)")
        else:
            print_success("Ollama already running on :11434")

        if not port_up(port):
            print_info(f"Starting API server on :{port}...")
            backend_proc = spawn(
                [sys.executable, str(root_dir / "core" / "api_server.py"),
                 "--host", "127.0.0.1", "--port", str(port)],
            )
            if not wait_port(port, 60):
                print_error(f"API server failed to start on :{port}")
                raise typer.Exit(1)
            print_success(f"API server running on :{port}")
        else:
            print_success(f"API server already running on :{port}")

        npm = "npm.cmd" if os.name == "nt" else "npm"
        release_bin = root_dir / "src-tauri" / "target" / "release" / ("palimind.exe" if os.name == "nt" else "palimind")
        if not skip_build:
            if not (root_dir / "node_modules").exists():
                print_info("Installing root dependencies (npm install)...")
                subprocess.run([npm, "install"], cwd=str(root_dir), check=True)
            print_info("Building Palimind app (tauri build — first run compiles Rust)...")
            subprocess.run([npm, "run", "build"], cwd=str(root_dir), check=True)
            print_success("Palimind app built")
        if release_bin.exists():
            print_info("Opening Palimind...")
            subprocess.Popen([str(release_bin)])
        else:
            print_info("No release build found — starting Tauri dev (first run compiles Rust)...")
            subprocess.run([npm, "run", "dev"], cwd=str(root_dir))

        print_success("Palimind closed.")

    except KeyboardInterrupt:
        print_info("Palimind stopped.")
    except subprocess.CalledProcessError as e:
        print_error(f"A setup step failed (exit {e.returncode}).")
        raise typer.Exit(1)
    finally:
        if not keep_backend:
            if backend_proc is not None:
                backend_proc.terminate()
                print_info("API server stopped.")
            if ollama_proc is not None:
                ollama_proc.terminate()
                print_info("Ollama stopped.")


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



