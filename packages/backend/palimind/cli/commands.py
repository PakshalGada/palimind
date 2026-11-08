from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from palimind.api import (
    IndexExistsError,
    IndexNotFoundError,
    NoContextError,
    PalimindError,
    initialize_index,
    query_stream,
    update_index,
)
from palimind.cli.ui import (
    console,
    create_progress,
    create_spinner,
    print_chat_ai_prefix,
    print_error,
    print_header,
    print_info,
    print_sources,
    print_startup_banner,
    print_success,
    print_summary_table,
    print_warning,
)

app = typer.Typer(help="Palimind - Local Multimodal RAG CLI")


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def npm_deps_stale(project_dir: Path) -> bool:
    """True when `npm install` is needed: node_modules is missing, or the
    manifest/lockfile changed (e.g. after a pull that added a dependency)
    since npm last wrote its install marker."""
    marker = project_dir / "node_modules" / ".package-lock.json"
    if not marker.exists():
        return True
    installed = _mtime(marker)
    return any(
        _mtime(project_dir / name) > installed for name in ("package.json", "package-lock.json")
    )


_FRONTEND_INPUTS = (
    "src",
    "public",
    "index.html",
    "package.json",
    "package-lock.json",
    "vite.config.ts",
)


def frontend_build_stale(frontend_dir: Path) -> bool:
    """True when dist is missing or any frontend source is newer than it, so a
    pulled UI change is never served from an old build."""
    built = _mtime(frontend_dir / "dist" / "index.html")
    if built == 0.0:
        return True
    for name in _FRONTEND_INPUTS:
        target = frontend_dir / name
        if target.is_dir():
            for child in target.rglob("*"):
                if child.is_file() and _mtime(child) > built:
                    return True
        elif _mtime(target) > built:
            return True
    return False


# Routes added since older local servers were started. A long-lived server
# keeps its original imports in memory even after `git pull` + frontend build,
# which used to leave the UI calling 404s such as /api/browser/state until the
# user manually killed the process. The launcher now detects and restarts it.
_REQUIRED_SERVER_ROUTES = (
    "/api/browser/state",
    "/api/browser/action",
    "/api/browser/frame",
    "/api/office/generate",
)


def missing_required_routes(openapi: dict) -> list[str]:
    paths = openapi.get("paths") if isinstance(openapi, dict) else None
    if not isinstance(paths, dict):
        return list(_REQUIRED_SERVER_ROUTES)
    return [route for route in _REQUIRED_SERVER_ROUTES if route not in paths]


def read_server_openapi(port: int, timeout: float = 2.0) -> dict | None:
    """Fetch the running server's OpenAPI document, or None when unreachable."""
    import json
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/openapi.json", timeout=timeout
        ) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return None
    return data if isinstance(data, dict) else None


def server_is_current(port: int) -> bool:
    """False when a live API server predates the routes this build requires.

    When the probe cannot read the document we do not kill an unknown process;
    only a parsed document that is missing routes triggers a restart.
    """
    openapi = read_server_openapi(port)
    if openapi is None:
        return True
    return not missing_required_routes(openapi)


def stop_api_server(port: int) -> bool:
    """Stop the Palimind API server listening on *port*.

    Returns False when the listener is not recognisably a Palimind API server,
    so the launcher never kills an unrelated process that happens to own the
    port.
    """
    try:
        import psutil
    except ImportError:
        return False

    listener: psutil.Process | None = None
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.status != psutil.CONN_LISTEN or not conn.laddr:
                continue
            if getattr(conn.laddr, "port", None) != port or conn.pid is None:
                continue
            try:
                candidate = psutil.Process(conn.pid)
                cmdline = " ".join(candidate.cmdline()).lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if "palimind.api_server" in cmdline or (
                "uvicorn" in cmdline and "palimind" in cmdline
            ):
                listener = candidate
                break
    except (psutil.AccessDenied, OSError):
        return False

    if listener is None:
        return False
    try:
        children = listener.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        children = []
    try:
        for child in children:
            try:
                child.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        listener.terminate()
        gone, alive = psutil.wait_procs([listener, *children], timeout=8)
        for proc in alive:
            try:
                proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return False


config_app = typer.Typer(help="Manage PaliMind configuration")
app.add_typer(config_app, name="config")

backup_app = typer.Typer(help="Local backup, verify and restore")
app.add_typer(backup_app, name="backup")

agent_app = typer.Typer(help="Drive agents through the local scripts API")
app.add_typer(agent_app, name="agent")


def _automation_connection() -> tuple[str, str]:
    from palimind.security.tokens import palimind_home

    folder = palimind_home() / "automation"
    try:
        url = (folder / "url").read_text("utf-8").strip()
        token = (folder / "token").read_text("utf-8").strip()
    except OSError:
        print_error("Local scripts are not enabled. Turn them on for an agent in Settings.")
        raise typer.Exit(5)
    if not url or not token:
        print_error("Local scripts are not enabled. Turn them on for an agent in Settings.")
        raise typer.Exit(5)
    return url, token


def _automation_call(method: str, path: str, body: dict | None = None) -> dict:
    import json
    import urllib.error
    import urllib.request

    url, token = _automation_connection()
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{url}{path}", data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read() or b"{}")
        except Exception:
            payload = {"error": str(exc)}
        payload["_status"] = exc.code
        return payload
    except Exception as exc:  # noqa: BLE001
        print_error(str(exc))
        raise typer.Exit(1)


@agent_app.command("list")
def agent_list():
    """List agents that allow local scripts."""
    payload = _automation_call("GET", "/v1/agents")
    for item in payload.get("agents") or []:
        routines = ", ".join(r.get("name", "") for r in item.get("routines") or [])
        console.print(f"  {item.get('name')}  {item.get('id')}  {routines}")


@agent_app.command("run")
def agent_run(
    agent: str = typer.Argument(..., help="Agent name or id"),
    task: str = typer.Argument(..., help="Task text; '-' reads stdin"),
    wait: bool = typer.Option(False, "--wait", help="Wait for the turn answer"),
    timeout: str = typer.Option("30m", "--timeout", help="Wait timeout"),
):
    """Send a task to an agent, optionally waiting for its answer."""
    if task == "-":
        import sys

        task = sys.stdin.read()
    payload = _automation_call("POST", f"/v1/agents/{agent}/messages", {"text": task})
    if payload.get("_status"):
        print_error(str(payload.get("error") or payload.get("_status")))
        raise typer.Exit(1)
    delivery_id = payload.get("messageId")
    print_info(f"delivery {delivery_id}")
    if not wait or not delivery_id:
        return
    import time

    seconds = _duration_seconds(timeout)
    deadline = time.time() + seconds
    while time.time() < deadline:
        status = _automation_call("GET", f"/v1/agents/{agent}/deliveries/{delivery_id}")
        if status.get("status") in ("completed", "failed", "interrupted", "cancelled"):
            if status.get("answer"):
                console.print(status["answer"])
            if status.get("status") != "completed":
                print_error(str(status.get("error") or status.get("status")))
                raise typer.Exit(1)
            return
        time.sleep(2)
    print_error("wait timed out")
    raise typer.Exit(4)


def _duration_seconds(value: str) -> float:
    raw = str(value or "30m").strip().lower()
    try:
        if raw.endswith("h"):
            return float(raw[:-1]) * 3600
        if raw.endswith("m"):
            return float(raw[:-1]) * 60
        if raw.endswith("s"):
            return float(raw[:-1])
        return float(raw)
    except ValueError:
        return 1800.0


@agent_app.command("status")
def agent_status(agent: str = typer.Argument(...), delivery: str = typer.Argument(...)):
    """Read one delivery by id."""
    payload = _automation_call("GET", f"/v1/agents/{agent}/deliveries/{delivery}")
    console.print_json(data=payload)


@agent_app.command("set-model")
def agent_set_model(
    agent: str = typer.Argument(...),
    model: str = typer.Argument(...),
    effort: str = typer.Option("", "--effort", help="Reasoning effort"),
):
    """Change an agent's model and optional effort."""
    body = {"model": model}
    if effort:
        body["reasoning_effort"] = effort
    payload = _automation_call("POST", f"/v1/agents/{agent}/settings", body)
    if payload.get("_status"):
        print_error(str(payload.get("error") or payload.get("_status")))
        raise typer.Exit(1)
    print_success(f"{payload.get('name')} → {payload.get('model')}")


@agent_app.command("new-chat")
def agent_new_chat(agent: str = typer.Argument(...)):
    """Clear the provider context while keeping visible messages."""
    payload = _automation_call("POST", f"/v1/agents/{agent}/context/clear", {})
    if payload.get("_status"):
        print_error(str(payload.get("error") or payload.get("_status")))
        raise typer.Exit(1)
    print_success("New chat started.")


@backup_app.command("list")
def backup_list():
    """List local backup archives."""
    from palimind.backup import list_backups

    items = list_backups()
    if not items:
        print_info("No backups found.")
        return
    for item in items:
        console.print(
            f"  {item['name']}  {item['size']} bytes  "
            f"{'encrypted' if item['encrypted'] else 'plain'}"
        )


@backup_app.command("create")
def backup_create(
    path: Optional[Path] = typer.Option(None, "--path", "-p", help="Output archive path"),
    label: str = typer.Option("", "--label", help="Human-readable backup label"),
    passphrase: str = typer.Option("", "--passphrase", help="Optional encryption passphrase"),
    include_workspace: list[Path] = typer.Option(
        [], "--include-workspace", help="Also back up a workspace's .palimind folder"
    ),
):
    """Create a local backup archive."""
    from palimind.backup import create_backup

    try:
        meta = create_backup(
            path,
            label=label,
            passphrase=passphrase,
            include_workspaces=list(include_workspace),
        )
    except Exception as exc:
        print_error(str(exc))
        raise typer.Exit(1) from exc
    print_success(f"Backup created: {meta['path']} ({meta['files']} files)")
    if meta.get("encrypted"):
        print_info("Archive is encrypted.")


@backup_app.command("verify")
def backup_verify(
    archive: Path = typer.Argument(..., help="Backup archive"),
    passphrase: str = typer.Option("", "--passphrase"),
):
    """Validate a backup's manifest and file hashes."""
    from palimind.backup import verify_backup

    try:
        result = verify_backup(archive, passphrase)
    except Exception as exc:
        print_error(str(exc))
        raise typer.Exit(1) from exc
    print_success(f"Backup is valid ({result['files']} files, version {result['version']})")


@backup_app.command("restore")
def backup_restore(
    archive: Path = typer.Argument(..., help="Backup archive"),
    target: Optional[Path] = typer.Option(None, "--target", help="Restore target home"),
    passphrase: str = typer.Option("", "--passphrase"),
    overwrite: bool = typer.Option(True, "--overwrite/--no-overwrite"),
    restore_workspaces: bool = typer.Option(False, "--restore-workspaces"),
    yes: bool = typer.Option(False, "--yes", help="Confirm overwriting local files"),
):
    """Restore a backup into the local PaliMind home."""
    from palimind.backup import restore_backup

    if not yes:
        print_error("Restore requires --yes to confirm.")
        raise typer.Exit(1)
    try:
        result = restore_backup(
            archive,
            passphrase=passphrase,
            target_home=target,
            overwrite=overwrite,
            restore_workspaces=restore_workspaces,
        )
    except Exception as exc:
        print_error(str(exc))
        raise typer.Exit(1) from exc
    print_success(
        f"Restored {result['restored']} files to {result['target_home']} "
        f"({result['skipped']} skipped)"
    )


@config_app.command("theme")
def set_theme(
    name: str = typer.Argument(..., help="Theme name: teal, purple, amber, blue, coral"),
    path: Path = typer.Option(Path("."), "--path", "-p"),
):
    """Set the accent color theme for the CLI."""
    from palimind.cli.ui import THEMES, console, print_error, print_success
    from palimind.config import load_config, save_config

    if name not in THEMES:
        print_error(f'Unknown theme: "{name}"\n')
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
    from palimind.config import load_config

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
    from palimind.config import load_config

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
    print_summary_table(
        [
            ("Files Indexed", str(result.indexed_files)),
            ("Chunks Created", str(result.chunks_indexed)),
            ("Deleted", str(result.deleted_files)),
            ("Unchanged", str(result.unchanged_files)),
        ]
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
    from palimind.config import load_config

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
    port: int = typer.Option(
        8000, "--port", help="Backend API port (window loads http://127.0.0.1:<port>/ui)"
    ),
    skip_install: bool = typer.Option(
        False,
        "--skip-install",
        help="Skip dependency installation (the frontend is still built if dist is missing)",
    ),
    keep_backend: bool = typer.Option(
        False, "--keep-backend", help="Keep Ollama/API server running after the app closes"
    ),
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
    from palimind.config import load_config

    config = load_config(target_dir)

    print_startup_banner(config)
    print_header("Palimind Launcher", config)

    # commands.py sits at <repo>/packages/backend/palimind/cli/commands.py
    repo_root = Path(__file__).resolve().parents[4]
    root_dir = repo_root / "packages" / "backend"  # python package (pip -e target, backend cwd)
    frontend_dir = repo_root / "packages" / "frontend"
    backend_proc: subprocess.Popen | None = None
    ollama_proc: subprocess.Popen | None = None

    def port_up(p: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.25)
            return s.connect_ex(("127.0.0.1", p)) == 0

    def wait_port(p: int, timeout: float, proc: subprocess.Popen | None = None) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if port_up(p):
                return True
            if proc is not None and proc.poll() is not None:
                return False  # the server crashed on startup; don't wait out the timeout
            time.sleep(0.4)
        return False

    def stop_tree(proc: subprocess.Popen) -> None:
        """Stop *proc* and its children (``ollama serve`` spawns model runners).

        ``Popen.terminate()`` alone only signals the direct child: on Windows
        TerminateProcess never reaches the runners, which kept holding RAM/VRAM
        after the app closed.
        """
        if proc.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                import signal

                # spawn() used start_new_session, so the pid is the group id.
                os.killpg(proc.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

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
            if npm_deps_stale(repo_root):
                print_info("Installing root dependencies (npm install)...")
                subprocess.run([npm, "install"], cwd=str(repo_root), check=True)
            else:
                print_success("Root dependencies installed")

            if npm_deps_stale(frontend_dir):
                print_info("Installing frontend dependencies (npm install)...")
                subprocess.run([npm, "install"], cwd=str(frontend_dir), check=True)
            else:
                print_success("Frontend dependencies installed")

        if frontend_build_stale(frontend_dir):
            # `--skip-install` skips dependency installation, not the build:
            # Tauri cannot load a UI that was never built. Fail with an
            # actionable message only when npm itself is unavailable.
            npm = "npm.cmd" if os.name == "nt" else "npm"
            if shutil.which(npm) is None:
                print_error(
                    "frontend dist is missing and npm was not found. Install Node.js, "
                    "then run: npm run build --prefix packages/frontend"
                )
                raise typer.Exit(1)
            print_info("Frontend build missing or out of date — building it now...")
            subprocess.run([npm, "run", "build"], cwd=str(frontend_dir), check=True)
        print_success("Frontend ready")

        # Credentials are configured once in the app's Settings and reused from
        # then on — never collected from the terminal. Local Ollama models work
        # without an OpenCode key, so this is advisory only.
        from palimind.opencode.auth import get_key

        try:
            authenticated = get_key() is not None
        except (OSError, ValueError):
            authenticated = False
        if authenticated:
            print_success("OpenCode already authenticated")
        else:
            print_warning(
                "OpenCode API key not set — add it in Settings to use cloud "
                "models (local models work without it)."
            )

        if not port_up(11434):
            ollama_bin = shutil.which("ollama")
            if ollama_bin:
                print_info("Starting Ollama server...")
                ollama_proc = spawn([ollama_bin, "serve"])
                if wait_port(11434, 20, ollama_proc):
                    print_success("Ollama running on :11434")
                else:
                    print_warning("Ollama did not respond on :11434 yet — continuing")
            else:
                print_warning("Ollama not found on PATH — skipping (local models unavailable)")
        else:
            print_success("Ollama already running on :11434")

        if port_up(port) and not server_is_current(port):
            print_warning(
                f"API server on :{port} is out of date (missing browser/office routes) "
                "— restarting it so the app and backend match this build."
            )
            if not stop_api_server(port):
                print_error(
                    f"Could not stop the old API server on :{port}. Stop that process "
                    "manually, then run `pm ui` again."
                )
                raise typer.Exit(1)
            deadline = time.time() + 10
            while port_up(port) and time.time() < deadline:
                time.sleep(0.25)
            if port_up(port):
                print_error(f"The old API server is still holding :{port}.")
                raise typer.Exit(1)
            print_success("Stopped the stale API server")

        if not port_up(port):
            import tempfile

            from palimind.settings import SERVER_HOST

            print_info(f"Starting API server on :{port}...")
            # Keep the server's output so a startup failure can be explained
            # instead of only reporting "failed to start".
            server_log = Path(tempfile.gettempdir()) / "palimind-api-server.log"
            server_log_fh = open(server_log, "wb")  # noqa: SIM115 - closed below
            try:
                backend_proc = spawn(
                    [
                        sys.executable,
                        "-m",
                        "palimind.api_server",
                        "--host",
                        SERVER_HOST,
                        "--port",
                        str(port),
                    ],
                    stdout=server_log_fh,
                    stderr=subprocess.STDOUT,
                )
            finally:
                server_log_fh.close()  # the child keeps its own handle
            if not wait_port(port, 60, backend_proc):
                print_error(f"API server failed to start on :{port}")
                try:
                    tail = server_log.read_text(errors="replace").strip().splitlines()[-20:]
                except OSError:
                    tail = []
                for line in tail:
                    print_info(f"  {line}")
                print_info(f"Full server log: {server_log}")
                raise typer.Exit(1)
            print_success(f"API server running on :{port} ({SERVER_HOST})")
        else:
            print_success(f"API server already running on :{port}")

        npm = "npm.cmd" if os.name == "nt" else "npm"
        print_info(f"Starting Palimind via 'tauri dev' (backend port {port})...")
        try:
            # The Tauri wrapper script reads these to override devUrl/window URL
            # and to poll the same port the backend is actually listening on.
            child_env = dict(os.environ)
            child_env["PALIMIND_API_PORT"] = str(port)
            child_env["PALIMIND_API_URL"] = f"http://127.0.0.1:{port}"
            # root package.json delegates to apps/desktop where the Tauri CLI lives
            subprocess.run([npm, "run", "dev"], cwd=str(repo_root), check=True, env=child_env)
        except subprocess.CalledProcessError as e:
            print_error(f"Tauri dev failed (exit {e.returncode}).")
            raise typer.Exit(1)

        print_success("Palimind closed.")

    except KeyboardInterrupt:
        print_info("Palimind stopped.")
    except subprocess.CalledProcessError as e:
        print_error(f"A setup step failed (exit {e.returncode}).")
        raise typer.Exit(1)
    finally:
        if not keep_backend:
            if backend_proc is not None:
                stop_tree(backend_proc)
                print_info("API server stopped.")
            if ollama_proc is not None:
                stop_tree(ollama_proc)
                print_info("Ollama stopped.")


@app.command()
def hotkey(
    action: str = typer.Argument(
        "start",
        help="Action: 'start' to begin listening, 'stop' to stop, 'trigger' to run manually (for Wayland)",
    ),
    hotkey_combo: str = typer.Option(
        "ctrl+shift+e", "--hotkey", "-k", help="Hotkey combination (e.g., 'ctrl+shift+e')"
    ),
    api_url: str = typer.Option("http://localhost:8000", "--api-url", help="FastAPI server URL"),
    path: Path = typer.Option(Path("."), "--path", "-p", help="Workspace path"),
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
        from palimind.hotkey.manager import HotkeyConfig, HotkeyManager
    except ImportError:
        print_error("Hotkey feature requires extra dependencies.")
        print_info("Install with: pip install -e '.\\[hotkey]'")
        raise typer.Exit(1)

    action = action.lower().strip()

    target_dir = path.resolve()
    from palimind.config import load_config

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
                    f"Captured to '{event.selected_field.name}': {len(event.selected_text)} chars"
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
                    f"Captured to '{event.selected_field.name}': {len(event.selected_text)} chars"
                )
                status["done"] = True

            manager.event_callback = on_event
            # Synchronous: the capture has fully finished when this returns.
            # (Polling afterwards only stalled for 60s when nothing was
            # captured, e.g. an empty clipboard.)
            event = manager._on_hotkey_pressed(sync=True)
            if event is None and not status["done"]:
                print_warning("Nothing captured — copy some text and make sure a field is set.")
                raise typer.Exit(1)

        except typer.Exit:
            raise

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
