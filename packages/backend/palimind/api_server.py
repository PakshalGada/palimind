import asyncio
import json
import os as _os
import platform
import re
import subprocess
import sys as _sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from dataclasses import field as _dc_field
from pathlib import Path
from typing import Any

# ── Cap native thread pools BEFORE any heavy lib (torch/onnxruntime/OpenMP)
# ── is imported. Without this, OCR/rerank/indexing can spin up dozens of
# ── worker threads that busy-wait a CPU core and wedge the API server.
for _k, _v in (
    ("OMP_NUM_THREADS", "2"),
    ("OMP_WAIT_POLICY", "PASSIVE"),
    ("OMP_PROC_BIND", "false"),
    ("MKL_NUM_THREADS", "2"),
    ("OPENBLAS_NUM_THREADS", "2"),
    ("VECLIB_MAXIMUM_THREADS", "2"),
    ("NUMEXPR_NUM_THREADS", "2"),
):
    _os.environ.setdefault(_k, _v)


def _detach_stdio() -> None:
    """
    Redirect OS-level file descriptors 1 (stdout) and 2 (stderr) to /dev/null.

    When Tauri spawns this server without explicitly redirecting its child
    stdio, the server inherits Tauri's PTY.  If that PTY later disconnects
    (window hide, resize, close) any write to fd 1 or fd 2 raises
    [Errno 5] EIO / [Errno 9] EBADF, which propagates as an unhandled
    OSError through the SSE generators and appears in the UI as
    "Stream error: [Errno 5] Input/output error".

    Using os.dup2() operates at the C level, so it protects every codepath:
    Python print(), sys.stdout.write(), C-extensions, uvicorn's logger, etc.
    The redirect is intentionally permanent for the life of the server process.
    """
    try:
        devnull_fd = _os.open(_os.devnull, _os.O_WRONLY)
        try:
            _os.dup2(devnull_fd, 1)  # stdout → /dev/null
            _os.dup2(devnull_fd, 2)  # stderr → /dev/null
        finally:
            _os.close(devnull_fd)
        # Also redirect the Python-level objects so sys.stdout.write() is safe
        _sys.stdout = open(_os.devnull, "w", encoding="utf-8")
        _sys.stderr = open(_os.devnull, "w", encoding="utf-8")
    except Exception:
        pass  # never crash the server over a logging redirect


import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from palimind import config as _palimind_config
from palimind.agents.api import router as agents_router
from palimind.agents.browser_profiles_api import router as browser_profiles_router
from palimind.agents.channels_api import router as channels_router
from palimind.agents.flows_api import router as flows_router
from palimind.agents.memory_api import router as memory_router
from palimind.agents.providers_api import router as providers_router
from palimind.agents.sharing_api import router as sharing_router
from palimind.agents.tasks_api import router as agent_tasks_router
from palimind.agents.teams_api import router as teams_router
from palimind.agents.usage_api import router as usage_router
from palimind.agents.visuals_api import router as visuals_router
from palimind.agents.webhooks_api import router as webhooks_router
from palimind.api import (
    IndexNotFoundError,
    initialize_index,
    require_index,
    update_index,
)
from palimind.api_routers.routers.backup import router as backup_router
from palimind.api_routers.routers.config import (
    moe_hardware_check as moe_hardware_check,  # noqa: F401
)
from palimind.api_routers.routers.config import router as config_router
from palimind.api_routers.routers.cookbook import router as cookbook_router
from palimind.api_routers.routers.desktop import router as desktop_router
from palimind.api_routers.routers.document import router as document_router
from palimind.api_routers.routers.files import router as files_router
from palimind.api_routers.routers.images import router as images_router
from palimind.api_routers.routers.index_runs import router as index_runs_router
from palimind.api_routers.routers.jobs import router as jobs_router
from palimind.api_routers.routers.mcp import router as mcp_router
from palimind.api_routers.routers.media import router as media_router
from palimind.api_routers.routers.metrics import router as metrics_router
from palimind.api_routers.routers.models import router as models_router
from palimind.api_routers.routers.research import router as research_router
from palimind.api_routers.routers.search import router as search_router
from palimind.api_routers.routers.tasks import router as tasks_router
from palimind.api_routers.routers.uploads import router as uploads_router
from palimind.api_routers.routers.voice import router as voice_router
from palimind.artifacts.api import router as artifacts_router
from palimind.document.stream import document_mode_stream
from palimind.events import hub as event_hub
from palimind.events import sse as event_sse
from palimind.events import store as event_store
from palimind.llm.stream import deep_research_mode_stream, llm_mode_stream, moe_mode_stream

# `@agent-name` mention anywhere in a chat turn. Emails (a@b) do not match
# because the `@` must follow whitespace or the start of the message.
_AGENT_MENTION_RE = re.compile(r"(^|\s)@([A-Za-z0-9][A-Za-z0-9_-]*)")


def _split_agent_mention(text: str) -> tuple[str | None, str]:
    """Return (mentioned agent name, input without the mention token)."""
    match = _AGENT_MENTION_RE.search(text or "")
    if not match:
        return None, text
    name = match.group(2).strip()
    stripped = (text[: match.start()] + text[match.end() :]).strip()
    return name or None, stripped
from palimind.memory.session_store import (
    add_new_session,
    delete_session,
    delete_session_message,
    load_sessions,
    set_active_session_id,
    truncate_session_messages,
)
from palimind.metrics import MetricsMiddleware
from palimind.openai_compat import router as openai_router
from palimind.projects.api import router as projects_router
from palimind.security.auth import install_auth
from palimind.security.tokens import get_api_token
from palimind.workflows.api import router as workflows_router

app = FastAPI(title="Palimind V2 API")

# CORS is limited to loopback origins. The UI is normally same-origin; the
# extra ports cover `vite` dev servers. Never allow `*` with credentials.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Every /api/* and /v1/* request must present the per-install bearer token.
# Loading /ui sets an HttpOnly same-origin cookie so the browser app (and
# EventSource) authenticates automatically.
install_auth(
    app,
    token_provider=get_api_token,
    protected_prefixes=("/api", "/v1"),
    cookie_path_prefix="/ui",
)
app.add_middleware(MetricsMiddleware)

app.include_router(teams_router)
app.include_router(agents_router)
app.include_router(agent_tasks_router)
app.include_router(channels_router)
app.include_router(browser_profiles_router)
app.include_router(providers_router)
app.include_router(flows_router)
app.include_router(usage_router)
app.include_router(memory_router)
app.include_router(sharing_router)
app.include_router(visuals_router)
app.include_router(webhooks_router)
app.include_router(projects_router)
app.include_router(artifacts_router)
app.include_router(openai_router)
app.include_router(workflows_router)
app.include_router(uploads_router)
app.include_router(tasks_router)
app.include_router(research_router)
app.include_router(search_router)
app.include_router(mcp_router)
app.include_router(index_runs_router)
app.include_router(images_router)
app.include_router(jobs_router)
app.include_router(document_router)
app.include_router(files_router)
app.include_router(cookbook_router)
app.include_router(desktop_router)
app.include_router(config_router)
app.include_router(backup_router)
app.include_router(media_router)
app.include_router(metrics_router)
app.include_router(models_router)
app.include_router(voice_router)


# Built frontend lives at packages/frontend/dist (repo layout: backend package
# sits two levels deeper). Fall back to the legacy sibling layout if present.
_FRONTEND_ROOTS = [
    Path(__file__).parent.parent.parent / "frontend" / "dist",
    Path(__file__).parent.parent / "frontend" / "dist",
]
UI_DIR = next((p for p in _FRONTEND_ROOTS if p.exists()), _FRONTEND_ROOTS[0])


class SPAStaticFiles(StaticFiles):
    """Serve index.html for unknown paths so the SPA can route client-side."""

    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException:
            response = None
        if response is None:
            # File/dir not found → fall back to the SPA entry point
            response = await super().get_response("index.html", scope)
        # Never cache HTML: the webview would otherwise keep the stale
        # index.html that references old hashed bundles that no longer exist,
        # leaving the app blank/broken after a frontend rebuild.
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-store"
        return response


@app.get("/client", response_class=HTMLResponse, include_in_schema=False)
async def thin_web_client() -> HTMLResponse:
    """Public HTML shell for phones/tablets; API calls still need the token."""
    from palimind.web_client import CLIENT_HTML

    return HTMLResponse(CLIENT_HTML, headers={"Cache-Control": "no-store"})


if UI_DIR.exists():
    app.mount("/ui", SPAStaticFiles(directory=UI_DIR, html=True), name="ui")


# -- Global State & Config --
# Single source of truth with palimind.config so the server writes the same
# file load_global_config() reads (tests monkeypatch this module attribute).
GLOBAL_CONFIG_PATH = _palimind_config.GLOBAL_CONFIG_PATH


def _write_global_config(data: dict) -> None:
    """Atomically replace the global config file.

    Written to a temp file in the same directory and swapped in with
    ``os.replace`` so a crash mid-write never leaves a truncated JSON file.
    """
    path = Path(GLOBAL_CONFIG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with _os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, indent=2))
            fh.flush()
            _os.fsync(fh.fileno())
        _os.replace(tmp, path)
    except BaseException:
        try:
            _os.unlink(tmp)
        except OSError:
            pass
        raise


class AppState:
    active_field: Path | None = None
    fields: list[str] = []
    loop: asyncio.AbstractEventLoop | None = None
    watcher: Any = None
    is_indexing: bool = False
    indexing_status: str = ""

    def load(self):
        if GLOBAL_CONFIG_PATH.exists():
            try:
                data = json.loads(GLOBAL_CONFIG_PATH.read_text("utf-8"))
                self.fields = data.get("fields", [])
                active = data.get("active_field")
                if active and Path(active).exists():
                    self.active_field = Path(active)
            except Exception:
                pass

    def save(self):
        _write_global_config(
            {
                "fields": self.fields,
                "active_field": str(self.active_field) if self.active_field else None,
            }
        )


state = AppState()
state.load()


def _agent_chat_root(agent_id: str) -> Path:
    """Per-agent private store (sessions, config) under the agents folder."""
    from palimind.agents.chat import agent_session_root

    return agent_session_root(agent_id)


_agent_sessions_seeded: set[str] = set()


def _ensure_agent_sessions(agent_id: str) -> None:
    """Give each agent its own session store, seeded from its chat log.

    Agents keep their own conversation history. On first use we migrate the
    legacy per-agent chat log into a session so nothing is lost.
    """
    if not agent_id or agent_id in _agent_sessions_seeded:
        return
    _agent_sessions_seeded.add(agent_id)
    root = _agent_chat_root(agent_id)
    try:
        from palimind.memory.session_store import (
            append_message_to_session,
            get_sessions_index_file,
            has_session_data,
            load_sessions,
        )

        if get_sessions_index_file(root).exists() or has_session_data(root):
            return
        from palimind.agents.chat import read_chat

        history = read_chat(agent_id)
        if not history:
            return
        # load_sessions creates the agent's default session on first use.
        data = load_sessions(root)
        session_id = data.get("active_session_id")
        if not session_id:
            return
        for message in history:
            role = "system" if str(message.get("role")) == "agent" else "user"
            content = str(message.get("content", "") or "")
            if content:
                append_message_to_session(root, session_id, role, content)
    except Exception as e:
        print(f"[agents] failed to seed sessions for {agent_id}: {e}")


def _chat_root(scope: str) -> Path | None:
    """Resolve the session/config root for a chat scope.

    ``scope="chat"`` uses a global, knowledge-base-independent store under the
    user's home directory. ``scope="agent:<id>"`` uses that agent's own store
    so its conversations are kept entirely separate from global/field chat.
    ``scope="project:<id>"`` uses the project's private folder, which also holds
    its isolated index and artifacts. ``scope="field"`` (default) uses the
    active knowledge base.
    """
    if scope == "chat":
        return Path.home()
    if scope.startswith("agent:"):
        agent_id = scope.split(":", 1)[1].strip()
        return _agent_chat_root(agent_id) if agent_id else None
    if scope.startswith("project:"):
        project_id = scope.split(":", 1)[1].strip()
        if not project_id:
            return None
        try:
            from palimind.projects import kb
            from palimind.projects.store import get_project

            if get_project(project_id) is None:
                return None
            return kb.ensure_project_storage(project_id)
        except ValueError:
            return None
    return state.active_field


def _global_chat_config() -> dict:
    """Config for global chat scope — merges persisted global settings into defaults."""
    from palimind.config import load_global_config

    return load_global_config()


# -- Clipboard capture state --
captured_text: str = ""


def _read_clipboard() -> str:
    """Read clipboard text using platform-specific tools.

    On Wayland (Hyprland etc.), the frontend reads clipboard via JS
    ``navigator.clipboard.readText()``, which is more reliable than
    subprocess calls. This function is purely a fallback.
    """
    system = platform.system()
    try:
        if system == "Linux":
            # Wayland (wl-paste) first, then X11 (xclip) fallback
            for cmd in [
                ["wl-paste", "--no-newline"],
                ["wl-paste"],
                ["xclip", "-selection", "clipboard", "-o"],
            ]:
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
                    if result.returncode == 0 and result.stdout.strip():
                        return result.stdout.strip()
                except FileNotFoundError:
                    continue
                except (subprocess.TimeoutExpired, UnicodeDecodeError):
                    continue
        elif system == "Darwin":
            result = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                return result.stdout.strip()
        elif system == "Windows":
            result = subprocess.run(
                ["powershell", "-command", "Get-Clipboard"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
    except Exception:
        pass
    return ""


# -- Global Event Listeners for watcher notifications --
# (The live fan-out now lives in palimind.events.hub, which also persists IDs.)


async def broadcast_event(data: dict):
    """Persist a global event and push it to live subscribers.

    Persisting before fan-out is what makes ``Last-Event-ID`` replay reliable:
    a client that missed the live push can reconnect and catch up.
    """
    await event_hub.publish("global", data)


async def background_index_field(path: Path):
    state.is_indexing = True
    state.indexing_status = f"Indexing [{path.name}]..."
    await broadcast_event({"type": "indexing_start", "message": state.indexing_status})

    try:
        # Require or initialize index
        try:
            await asyncio.to_thread(require_index, path)
        except IndexNotFoundError:
            await asyncio.to_thread(initialize_index, path)

        await asyncio.to_thread(update_index, path)
        update_watcher(path)
    except Exception as e:
        print(f"Failed to index [{path.name}]: {e!r}")
        state.is_indexing = False
        state.indexing_status = ""
        await broadcast_event(
            {"type": "indexing_error", "message": f"Failed to index [{path.name}]: {e}"}
        )
        return

    # Indexing (crawl + parse + embed) is done — clear the UI state now. The
    # knowledge-graph build is a separate, optional LLM pass and must NOT hold
    # the "indexing" spinner: it was the main reason a 2-file folder felt slow.
    state.is_indexing = False
    state.indexing_status = ""
    await broadcast_event(
        {"type": "indexing_complete", "message": f"[{path.name}] indexed successfully!"}
    )
    await broadcast_event({"type": "sync", "message": f"[{path.name}] Context Updated"})

    try:
        from palimind.config import load_config

        cfg = load_config(path)
        if cfg.get("build_graph", True):
            ollama_url = cfg.get("ollama_base_url", "http://localhost:11434")
            light = cfg.get("light_model") or ""
            from palimind.document.graph import build_doc_graph_incremental

            await asyncio.to_thread(build_doc_graph_incremental, path, ollama_url, light)
            await broadcast_event(
                {"type": "graph_ready", "message": f"[{path.name}] knowledge graph ready"}
            )
    except Exception as e:
        print(f"Background graph build failed: {e}")


def handle_watcher_change(root: Path, changed_path: str = ""):
    print(f"Watcher: detected file changes in {root}.")
    # Auto-reindex is opt-in via config 'auto_reindex' (default off). A full
    # field reindex does CPU-heavy work (OCR, table extraction, embeddings)
    # that starves the async event loop and wedges the server — so by default
    # the watcher only fires watcher-mode agents and leaves indexing to manual
    # Sync. When enabled, it is single-flight: events during a running
    # reindex are skipped because update_index crawls the whole field anyway.
    from palimind.config import load_config
    from palimind.storage.db import INDEX_WRITE_LOCK

    cfg = load_config(root)
    if cfg.get("auto_reindex", False) and not INDEX_WRITE_LOCK.locked():
        try:
            result = update_index(root)
            print("Watcher: index updated successfully.")

            # Keep the knowledge graph in sync with the changed files.
            try:
                from palimind.document.graph import build_doc_graph_incremental

                build_doc_graph_incremental(
                    root, cfg.get("ollama_base_url", "http://localhost:11434")
                )
            except Exception as e:
                print(f"Watcher: incremental graph update failed: {e}")

            if state.loop:
                asyncio.run_coroutine_threadsafe(
                    broadcast_event(
                        {
                            "type": "sync",
                            "message": f"[{root.name}] Context Updated",
                            "indexed": result.indexed_files,
                            "deleted": result.deleted_files,
                        }
                    ),
                    state.loop,
                )
        except Exception as e:
            print(f"Watcher: index update failed: {e}")

    # Fire watcher-mode agents whose glob matches the changed file.
    try:
        from palimind.agents.scheduler import check_watcher_triggers

        check_watcher_triggers(root, changed_path)
    except Exception as e:
        print(f"Watcher: trigger dispatch failed: {e}")


def update_watcher(path: Path | None):
    """Start (or restart) the file watcher for the active field."""
    if state.watcher:
        try:
            state.watcher.stop()
        except Exception:
            pass
        state.watcher = None
    if path is None:
        return
    from palimind.core.watcher import FieldWatcher

    try:
        watcher = FieldWatcher(path, handle_watcher_change)
        watcher.start()
        state.watcher = watcher
        print(f"Watcher: watching {path}")
    except Exception as e:
        print(f"Watcher: failed to start for {path}: {e}")


def _add_capture_to_field(root: Path, text: str) -> dict:
    """Index a captured text snippet into a field's vector DB and rebuild the knowledge graph."""
    from palimind.config import load_config
    from palimind.core.embedder import generate_embedding
    from palimind.storage.db import get_connection, insert_chunks, upsert_file
    from palimind.storage.vector_store import VectorStore

    config = load_config(root)

    # Generate embedding
    embedding = generate_embedding(text, config["ollama_base_url"], config["embed_model"], root)
    if not embedding:
        return {"error": "Failed to generate embedding"}

    capture_id = str(uuid.uuid4())[:8]
    capture_path = f"_captures_/{capture_id}.md"

    conn = get_connection(root)
    try:
        file_id = upsert_file(conn, capture_path, capture_id, time.time())

        chunk_db_ids = insert_chunks(
            conn,
            file_id,
            [
                (0, "capture", text, "Capture", "", "", None, None, None),
            ],
        )

        # Insert into vector store
        with VectorStore(root) as vstore:
            vstore.insert(
                [
                    {
                        "vector": embedding,
                        "chunk_db_id": chunk_db_ids[0],
                        "file_path": capture_path,
                        "chunk_index": 0,
                        "chunk_type": "capture",
                        "content": text,
                        "section_title": "Capture",
                        "subsection": "",
                        "main_section": "Captures",
                        "parent_section": "",
                        "doc_year": None,
                        "doc_type": "capture",
                        "entity_name": "",
                    }
                ]
            )

        conn.commit()
    finally:
        conn.close()

    # Update knowledge graph incrementally in background
    try:
        from palimind.document.graph import build_doc_graph_incremental

        build_doc_graph_incremental(root, config["ollama_base_url"])
    except Exception as e:
        print(f"[capture] graph rebuild failed: {e}")

    return {"status": "success", "capture_id": capture_id}


def build_file_tree(root: Path, _max_depth: int = 10) -> list[dict]:
    def walk(path: Path, depth: int = 0) -> list[dict]:
        if depth >= _max_depth:
            return [{"name": "...", "path": "", "type": "truncated"}]
        items = []
        try:
            for entry in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                if entry.name in [
                    ".palimind",
                    ".git",
                    "node_modules",
                    "__pycache__",
                    ".venv",
                    "venv",
                    ".idea",
                    ".vscode",
                ]:
                    continue
                if entry.name.startswith("."):
                    continue

                rel_path = str(entry.relative_to(root))
                if entry.is_dir():
                    children = walk(entry, depth + 1)
                    items.append(
                        {
                            "name": entry.name,
                            "path": rel_path,
                            "type": "directory",
                            "children": children,
                        }
                    )
                else:
                    items.append({"name": entry.name, "path": rel_path, "type": "file"})
        except Exception:
            pass
        return items

    return walk(root)


@app.on_event("startup")
async def startup_event():
    state.loop = asyncio.get_running_loop()

    from palimind.agents.catalog import migrate_field_agents, migrate_field_chats
    from palimind.agents.goals import start_runner
    from palimind.agents.registry import set_registry_field
    from palimind.agents.run_journal import recover_interrupted
    from palimind.agents.runtime import record_run
    from palimind.agents.scheduler import start_scheduler

    # Promote journals left behind by a crash into normal "interrupted" run
    # history instead of silently losing those runs.
    try:
        await asyncio.to_thread(recover_interrupted, record_run)
    except Exception as exc:  # noqa: BLE001
        print(f"[agents] run-journal recovery failed: {exc}")

    # Checkpoints written by a previous process are ``running`` but nothing is
    # actually in flight at startup. Mark them resumable so the UI/API can
    # continue them instead of pretending they are still active.
    try:
        from palimind.agents import run_state as run_state_mod

        recovered_states = await asyncio.to_thread(run_state_mod.recover_interrupted)
        if recovered_states:
            print(f"[agents] {len(recovered_states)} run checkpoint(s) marked resumable")
    except Exception as exc:  # noqa: BLE001
        print(f"[agents] run-state recovery failed: {exc}")

    roots = list(state.fields)
    if state.active_field and state.active_field not in roots:
        roots.append(state.active_field)
    migrate_field_agents([Path(r) for r in roots])
    migrate_field_chats([Path(r) for r in roots])

    # Canvas was retired in favour of artifacts; carry any existing documents
    # into the global artifact library once.
    try:
        from palimind.artifacts.registry import migrate_canvas_documents

        await asyncio.to_thread(migrate_canvas_documents)
    except Exception as exc:  # noqa: BLE001
        print(f"[startup] canvas → artifact migration failed: {exc}")

    set_registry_field(state.active_field)
    try:
        from palimind.agents import threads

        created = await asyncio.to_thread(threads.ensure_all_chat_threads)
        if created:
            print(f"[agents] created {created} chat thread(s)")
    except Exception as exc:  # noqa: BLE001
        print(f"[startup] agent thread backfill failed: {exc}")
    try:
        from palimind.agents.lifecycle import remove_legacy_presets

        await asyncio.to_thread(remove_legacy_presets)
    except Exception as exc:  # noqa: BLE001
        print(f"[startup] preset cleanup failed: {exc}")
    start_scheduler(state.loop)
    start_runner()
    try:
        from palimind.jobs import start_runner as start_job_runner

        await start_job_runner()
    except Exception as exc:  # noqa: BLE001
        print(f"[startup] durable job runner failed: {exc}")
    try:
        from palimind.agents.queue import start_queue_runner

        start_queue_runner()
    except Exception as exc:  # noqa: BLE001
        print(f"[startup] queue runner failed: {exc}")
    try:
        from palimind import settings as _settings
        from palimind.agents import automation
        from palimind.agents.registry import get_registry as _get_registry

        if _settings.AGENT_AUTOMATION_ENABLE and any(
            bool(getattr(defn, "allow_automation", False)) for defn in _get_registry().all()
        ):
            automation.start_server()
    except Exception as exc:  # noqa: BLE001
        print(f"[startup] automation listener failed: {exc}")

    if state.active_field:
        # Surface embedding/index mismatches at startup instead of letting
        # semantic search silently degrade to keyword-only.
        try:
            from palimind.config import load_config
            from palimind.storage.vector_store import index_compatibility_error

            cfg = load_config(state.active_field)
            problem = index_compatibility_error(
                state.active_field,
                expected_model=cfg.get("embed_model"),
                expected_dim=cfg.get("embed_dim"),
            )
            if problem:
                import logging

                logging.getLogger("palimind.api_server").error(
                    "Vector index incompatible: %s", problem
                )
        except Exception as exc:  # noqa: BLE001
            print(f"[startup] index compatibility check failed: {exc}")
        update_watcher(state.active_field)


@app.on_event("shutdown")
async def shutdown_event():
    from palimind.agents.goals import stop_runner
    from palimind.agents.queue import stop_queue_runner
    from palimind.agents.scheduler import stop_scheduler

    stop_scheduler()
    stop_runner()
    try:
        from palimind.jobs import stop_runner as stop_job_runner

        await stop_job_runner()
    except Exception:
        pass
    try:
        stop_queue_runner()
    except Exception:
        pass
    try:
        from palimind.agents import automation

        automation.stop_server()
    except Exception:
        pass
    if state.watcher:
        try:
            state.watcher.stop()
        except Exception:
            pass


def _on_field_changed(field: Path | None) -> None:
    """Repoint the agent registry at the active field (no-op before startup)."""
    try:
        import asyncio as _aio

        from palimind.agents.registry import set_registry_field

        if _aio.get_running_loop() is not None:
            set_registry_field(field)
    except RuntimeError:
        pass


# -- Endpoints --

# ── Hotkey capture endpoints ────────────────────────────────────────────


@app.get("/")
async def root():
    """Root — points at the UI and health endpoints."""
    return {
        "status": "ok",
        "app": "Palimind",
        "ui": "/ui",
        "health": "/health",
        "ready": "/ready",
    }


@app.get("/health")
async def health_check():
    """Liveness probe (used by the Tauri shell, Docker, and scripts)."""
    return {"status": "ok", "app": "Palimind"}


@app.get("/ready")
async def readiness_check():
    """Readiness probe: reports whether the UI bundle is served."""
    return {"status": "ok" if UI_DIR.exists() else "degraded", "ui_served": UI_DIR.exists()}


@app.post("/api/select")
async def select_field(req: Request):
    """Save captured text to the chosen field's vector DB and knowledge graph."""
    global captured_text
    data = await req.json()
    path_str = data.get("path")

    if path_str is None:
        captured_text = ""
        return {"status": "cancelled"}

    field_path = Path(path_str).resolve()
    if not field_path.is_dir():
        return {"error": f"Field directory not found: {field_path}"}

    # Use text from frontend (preferred, reliable across all platforms)
    text = data.get("text", "").strip()

    # Fallback: read clipboard if frontend didn't send text
    if not text:
        if not captured_text:
            captured_text = await asyncio.to_thread(_read_clipboard)
        text = captured_text

    if not text:
        return {"error": "No text to capture — copy text first, then retry"}

    try:
        result = await asyncio.to_thread(_add_capture_to_field, field_path, text)
        if "error" in result:
            return result
        captured_text = ""
        return {"status": "success", "message": "Captured text saved to field"}
    except Exception:
        return {"error": "Failed to save capture"}


@app.post("/api/capture/file")
async def capture_file(req: Request):
    """Index an attached file's text into the active field as a capture.

    The frontend reads file contents (UTF-8 text) and posts them here so a
    dropped attachment becomes searchable by document-mode RAG before the
    follow-up chat query runs.
    """
    if not state.active_field:
        return {"error": "No active field"}
    data = await req.json()
    name = str(data.get("name", "attachment")).strip() or "attachment"
    content = str(data.get("content", ""))
    if not content.strip():
        return {"error": "No content to index"}
    try:
        if len(content) > 200_000:
            content = content[:200_000]
        text = f"[Attachment: {name}]\n{content}"
        result = await asyncio.to_thread(_add_capture_to_field, state.active_field, text)
        if "error" in result:
            return result
        return {"status": "success", "capture_id": result.get("capture_id")}
    except Exception:
        return {"error": "Failed to index field"}


@app.get("/api/fields")
async def get_fields():
    return {
        "fields": state.fields,
        "active_field": str(state.active_field) if state.active_field else None,
        "is_indexing": state.is_indexing,
        "indexing_status": state.indexing_status,
    }


def _select_dir_blocking():
    import subprocess
    import sys

    script = """
import tkinter as tk
from tkinter import filedialog
root = tk.Tk()
root.withdraw()
root.attributes('-topmost', True)
folder_path = filedialog.askdirectory(title="Select a directory for Palimind Field")
if folder_path:
    print(folder_path)
root.destroy()
"""
    try:
        res = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, timeout=180
        )
        if res.returncode == 0:
            path = res.stdout.strip()
            return path if path else None
    except Exception as e:
        print(f"Subprocess folder picker failed: {e}")
    return None


@app.post("/api/fields/select_dialog")
async def select_dialog():
    """Opens a native OS folder picker."""
    folder_path = await asyncio.to_thread(_select_dir_blocking)
    if folder_path:
        return {"path": str(Path(folder_path).resolve())}
    return {"path": None}


@app.get("/api/fs/list")
async def list_fs(path: str | None = None):
    target_path = None
    if path:
        target_path = Path(path).resolve()
    else:
        if state.active_field:
            target_path = state.active_field.resolve()
        else:
            target_path = Path.home()

    if not target_path.exists():
        target_path = Path.home()

    if not target_path.is_dir():
        target_path = target_path.parent

    # Prevent listing sensitive system directories
    _SENSITIVE_PATHS = {
        Path("/etc").resolve(),
        Path("/sys").resolve(),
        Path("/proc").resolve(),
        Path("/dev").resolve(),
        Path("/boot").resolve(),
        Path("/root").resolve(),
    }
    if target_path in _SENSITIVE_PATHS:
        return {"error": "Access to this directory is restricted"}

    current_path = str(target_path)
    parent_path = str(target_path.parent) if target_path.parent != target_path else None

    items = []
    try:
        for entry in sorted(target_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            # Hide hidden files/folders by default
            if entry.name.startswith("."):
                continue
            items.append(
                {
                    "name": entry.name,
                    "path": str(entry.resolve()),
                    "type": "directory" if entry.is_dir() else "file",
                }
            )
    except Exception:
        return {"error": "Failed to list directory"}

    return {"current_path": current_path, "parent_path": parent_path, "items": items}


@app.post("/api/fields/add")
async def add_field(req: Request):
    data = await req.json()
    path_str = data.get("path")
    if not path_str:
        return {"error": "Path is required"}

    path = Path(path_str).resolve()
    if not path.is_dir():
        return {"error": f"Directory not found: {path}"}

    path_key = str(path)
    is_new = path_key not in state.fields
    if is_new:
        state.fields.append(path_key)

    state.active_field = path
    state.save()

    # Index only the first time this folder is selected as a field.
    # Subsequent syncs happen via the "Sync Active Field" button.
    if is_new:
        asyncio.create_task(background_index_field(path))
        _on_field_changed(path)
        return {"status": "indexing", "field": path_key}
    _on_field_changed(path)
    return {"status": "ok", "field": path_key}


@app.post("/api/fields/remove")
async def remove_field(req: Request):
    data = await req.json()
    path_str = data.get("path")
    if not path_str:
        return {"error": "Path is required"}

    path_key = str(Path(path_str).resolve())
    if path_key in state.fields:
        state.fields.remove(path_key)

    if state.active_field and str(state.active_field) == path_key:
        state.active_field = None
        update_watcher(None)

    state.save()
    _on_field_changed(state.active_field)
    return {"status": "success"}


@app.post("/api/fields/set_active")
async def set_active_field(req: Request):
    data = await req.json()
    path_str = data.get("path")
    if not path_str:
        return {"error": "Path is required"}

    path = Path(path_str).resolve()
    if not path.is_dir():
        return {"error": f"Directory not found: {path}"}

    state.active_field = path
    if str(path) not in state.fields:
        state.fields.append(str(path))
    state.save()
    _on_field_changed(path)

    return {"status": "ok", "active_field": str(path)}


@app.post("/api/update")
async def api_update():
    if not state.active_field:
        return {"error": "No active field"}
    try:
        result = await asyncio.to_thread(update_index, state.active_field)

        # Fire and forget incremental graph update so we don't block the UI
        async def _build_graph():
            try:
                from palimind.config import load_config

                cfg = load_config(state.active_field)
                if not cfg.get("build_graph", True):
                    return
                ollama_url = cfg.get("ollama_base_url", "http://localhost:11434")
                light = cfg.get("light_model") or ""
                from palimind.document.graph import build_doc_graph_incremental

                await asyncio.to_thread(
                    build_doc_graph_incremental, state.active_field, ollama_url, light
                )
            except Exception as e:
                print(f"Background graph build failed: {e}")

        asyncio.create_task(_build_graph())

        return {
            "status": "success",
            "indexed_files": result.indexed_files,
            "deleted_files": result.deleted_files,
        }
    except Exception as e:
        print(f"Index update failed for {state.active_field}: {e!r}")
        return {"error": f"Failed to update index: {e}"}


# -- Endpoints --


@app.get("/api/sessions")
async def get_sessions(scope: str = "field"):
    root = _chat_root(scope)
    if root is None:
        return {"error": "No active knowledge base"}
    if scope.startswith("agent:"):
        await asyncio.to_thread(_ensure_agent_sessions, scope.split(":", 1)[1].strip())
    sessions_data = await asyncio.to_thread(load_sessions, root)
    return sessions_data


@app.post("/api/sessions/new")
async def create_session(req: Request, scope: str = "field"):
    root = _chat_root(scope)
    if root is None:
        return {"error": "No active knowledge base"}
    data = await req.json()
    name = data.get("name", "New Session")
    sessions_data = await asyncio.to_thread(add_new_session, root, name)
    return sessions_data


@app.post("/api/sessions/set_active")
async def set_active_session(req: Request, scope: str = "field"):
    root = _chat_root(scope)
    if root is None:
        return {"error": "No active knowledge base"}
    data = await req.json()
    session_id = data.get("session_id")
    if not session_id:
        return {"error": "session_id is required"}
    sessions_data = await asyncio.to_thread(set_active_session_id, root, session_id)
    return sessions_data


@app.post("/api/sessions/remove")
async def remove_session(req: Request, scope: str = "field"):
    root = _chat_root(scope)
    if root is None:
        return {"error": "No active knowledge base"}
    data = await req.json()
    session_id = data.get("session_id")
    if not session_id:
        return {"error": "session_id is required"}
    sessions_data = await asyncio.to_thread(delete_session, root, session_id)
    return sessions_data


@app.post("/api/sessions/truncate")
async def truncate_session(req: Request, scope: str = "field"):
    """Keep only the first ``keep_count`` messages (for regenerate/edit)."""
    root = _chat_root(scope)
    if root is None:
        return {"error": "No active knowledge base"}
    data = await req.json()
    session_id = data.get("session_id")
    if not session_id:
        return {"error": "session_id is required"}
    try:
        keep_count = int(data.get("keep_count", 0))
    except (TypeError, ValueError):
        return {"error": "keep_count must be an integer"}
    sessions_data = await asyncio.to_thread(truncate_session_messages, root, session_id, keep_count)
    return sessions_data


@app.post("/api/sessions/delete_message")
async def delete_message(req: Request, scope: str = "field"):
    """Delete a single message by index from a session."""
    root = _chat_root(scope)
    if root is None:
        return {"error": "No active knowledge base"}
    data = await req.json()
    session_id = data.get("session_id")
    if not session_id:
        return {"error": "session_id is required"}
    try:
        index = int(data.get("index", -1))
    except (TypeError, ValueError):
        return {"error": "index must be an integer"}
    sessions_data = await asyncio.to_thread(delete_session_message, root, session_id, index)
    return sessions_data


async def _run_agent_and_record(agent_id: str, prompt: str, session_id: str) -> str:
    """Run an agent and record the exchange in its own chat history."""
    from palimind.agents.registry import get_registry
    from palimind.agents.service import run_agent as run_agent_service
    from palimind.memory.session_store import append_message_to_session

    defn = await asyncio.to_thread(get_registry().get_by_id, agent_id)
    if defn is None:
        raise ValueError(f"Agent not found: {agent_id}")
    _ensure_agent_sessions(agent_id)
    root = _agent_chat_root(agent_id)
    data = await asyncio.to_thread(load_sessions, root)
    session_id_active = data.get("active_session_id")
    meta = {"agent_name": defn.name}
    if session_id_active:
        await asyncio.to_thread(
            append_message_to_session,
            root,
            session_id_active,
            "user",
            prompt,
            None,
            "agent",
            meta,
            None,
        )
    output = await run_agent_service(defn, prompt, session_id=session_id)
    if session_id_active:
        await asyncio.to_thread(
            append_message_to_session,
            root,
            session_id_active,
            "system",
            output,
            None,
            "agent",
            meta,
            None,
        )
    return output


@app.get("/api/events")
async def events_stream(request: Request, once: bool = False):
    """Global SSE feed with persisted IDs and ``Last-Event-ID`` replay.

    ``once=true`` replays the missed range and closes (useful for clients that
    only need a catch-up snapshot).
    """
    last_id = event_sse.last_event_id(request)
    stream = "global"
    queue = await event_hub.subscribe(stream)

    async def generator():
        sent = last_id
        try:
            if last_id:
                missed = await asyncio.to_thread(event_store.replay, stream, last_id, 2000)
                for event in missed:
                    sent = max(sent, int(event["event_id"]))
                    yield event_sse.format_event(event)
            if once:
                return
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                if int(event.get("event_id") or 0) <= sent:
                    continue
                sent = int(event["event_id"])
                yield event_sse.format_event(event)
        except asyncio.CancelledError:
            pass
        finally:
            await event_hub.unsubscribe(stream, queue)

    return StreamingResponse(generator(), media_type="text/event-stream")


@app.get("/api/streams/{stream_id}/events")
async def stream_events(
    stream_id: str,
    request: Request,
    tail: bool = False,
):
    """Replay/attach to a per-turn SSE stream (``chat:<stream_id>``).

    The browser can reconnect with its last event id after a dropped
    connection; ``tail=true`` keeps the connection open for live events.
    """
    stream = stream_id if ":" in stream_id else f"chat:{stream_id}"
    last_id = event_sse.last_event_id(request)
    queue = await event_hub.subscribe(stream) if tail else None

    async def generator():
        sent = last_id
        try:
            missed = await asyncio.to_thread(event_store.replay, stream, last_id, 5000)
            for event in missed:
                sent = max(sent, int(event["event_id"]))
                yield event_sse.format_event(event)
            if not tail or queue is None:
                return
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                if int(event.get("event_id") or 0) <= sent:
                    continue
                sent = int(event["event_id"])
                yield event_sse.format_event(event)
        except asyncio.CancelledError:
            pass
        finally:
            if queue is not None:
                await event_hub.unsubscribe(stream, queue)

    return StreamingResponse(generator(), media_type="text/event-stream")


@app.get("/api/files/tree")
async def get_files_tree():
    if not state.active_field:
        return {"error": "No active field"}
    tree = await asyncio.to_thread(build_file_tree, state.active_field)
    return {"tree": tree}


def list_directory_shallow(root: Path, subpath: str) -> list[dict]:
    root_resolved = root.resolve()
    target = (root / subpath).resolve() if subpath else root_resolved
    # Path traversal protection: ensure target is inside root
    if root_resolved != target and root_resolved not in target.parents:
        return []
    items = []
    try:
        for entry in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if entry.name in [
                ".palimind",
                ".git",
                "node_modules",
                "__pycache__",
                ".venv",
                "venv",
                ".idea",
                ".vscode",
            ]:
                continue
            if entry.name.startswith("."):
                continue
            items.append(
                {
                    "name": entry.name,
                    "path": str(entry.relative_to(root)),
                    "type": "directory" if entry.is_dir() else "file",
                }
            )
    except Exception:
        pass
    return items


@app.get("/api/files/tree/sub")
async def get_file_tree_sub(path: str = ""):
    if not state.active_field:
        return {"error": "No active field"}
    children = await asyncio.to_thread(list_directory_shallow, state.active_field, path)
    return {"children": children}


async def _agent_scope_chat(
    scope: str,
    q: str,
    session_id: str | None,
    entry: "_ChatStreamEntry | None" = None,
) -> StreamingResponse:
    """Route a chat to an agent, or to any agent mentioned in the message.

    The agent's conversations are stored in its own private session store, so
    they never mix with global or knowledge-base chat. A message may call a
    different agent with ``@name``; the reply stays in the same conversation
    and records the responding agent in its message metadata.
    """
    from palimind.agents.registry import get_registry
    from palimind.agents.service import agent_sse_stream
    from palimind.config import load_global_config
    from palimind.opencode.router import resolve_model_url

    agent_id = scope.split(":", 1)[1].strip()
    defn = get_registry().get_by_id(agent_id)
    if defn is None or not defn.enabled:

        async def err_stream():
            msg = "Agent not found" if defn is None else "Agent is disabled"
            yield f"data: {json.dumps({'type': 'error', 'text': msg})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        return StreamingResponse(err_stream(), media_type="text/event-stream")

    responder = defn
    agent_input = q
    candidate, stripped = _split_agent_mention(q)
    if candidate:
        other = get_registry().get(candidate)
        if other is not None and other.enabled:
            responder = other
            agent_input = stripped

    _ensure_agent_sessions(agent_id)
    global_cfg = load_global_config()
    ollama_url = global_cfg.get("ollama_base_url", "http://localhost:11434")
    model = responder.model or global_cfg.get("chat_model", "llama3")
    agent_root = _agent_chat_root(agent_id)
    session_id = await _resolve_chat_session(agent_root, session_id)
    if entry is not None:
        entry.bind(
            agent_root,
            session_id,
            mode="agent",
            mode_params={"agent_name": responder.name, "agent_id": responder.id},
        )
    return await agent_sse_stream(
        agent_root,
        responder.name,
        agent_input or "Run your task.",
        session_id,
        await asyncio.to_thread(resolve_model_url, model, ollama_url),
        model,
        working_root=None,
        prefix_mention=False,
        chat_style=True,
    )


# ── Chat stream registry (session event + Stop) ─────────────────────────
_STREAM_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


@dataclass
class _ChatStreamEntry:
    """Server-side view of one in-flight /api/chat stream.

    ``text`` mirrors the answer the client has been sent (same rules as the
    frontend stream reducer), so Stop can persist exactly what the user saw.
    """

    stream_id: str
    root: Path | None = None
    session_id: str | None = None
    mode: str = ""
    mode_params: dict | None = None
    text: str = ""
    sources: list[str] | None = None
    citations: dict | None = None
    started: bool = False
    finished: bool = False
    cancelled: bool = False
    stop_lock: asyncio.Lock = _dc_field(default_factory=asyncio.Lock)
    stop_result: dict | None = None

    def bind(
        self,
        root: Path | None,
        session_id: str | None,
        mode: str = "",
        mode_params: dict | None = None,
    ) -> None:
        self.root = root
        self.session_id = session_id
        self.mode = mode
        self.mode_params = mode_params

    def observe(self, chunk: Any) -> None:
        """Track the visible answer from one SSE chunk."""
        if isinstance(chunk, bytes | memoryview):
            chunk = bytes(chunk).decode("utf-8", "replace")
        for line in str(chunk).splitlines():
            if not line.startswith("data:"):
                continue
            try:
                event = json.loads(line[5:].strip())
            except (ValueError, TypeError):
                continue
            if isinstance(event, dict):
                self._apply(event)

    def _apply(self, event: dict) -> None:
        etype = event.get("type")
        text = event.get("text")
        if etype == "token" or (etype == "agent:token" and not event.get("reset")):
            if isinstance(text, str):
                self.text += text
        elif etype == "agent:token":
            self.text = ""
        elif etype == "answer_final":
            if isinstance(text, str) and text:
                self.text = text
        elif etype == "agent:completed":
            output = str(event.get("output") or "").strip()
            if output:
                self.text = output
        elif etype == "citation_map":
            self.citations = {k: v for k, v in event.items() if k != "type"}
            if isinstance(text, str) and text:
                self.text = text
        elif etype == "sources":
            srcs = event.get("sources")
            self.sources = [str(x) for x in srcs] if isinstance(srcs, list) else None
        elif etype == "done":
            self.finished = True


_CHAT_STREAMS: dict[str, _ChatStreamEntry] = {}


def _register_chat_stream(stream_id: str | None) -> _ChatStreamEntry:
    sid = (stream_id or "").strip()
    if not _STREAM_ID_RE.match(sid) or sid in _CHAT_STREAMS:
        sid = uuid.uuid4().hex
    entry = _ChatStreamEntry(stream_id=sid)
    _CHAT_STREAMS[sid] = entry
    return entry


def _unregister_chat_stream(entry: _ChatStreamEntry) -> None:
    if _CHAT_STREAMS.get(entry.stream_id) is entry:
        del _CHAT_STREAMS[entry.stream_id]


async def _resolve_chat_session(root: Path, session_id: str | None) -> str | None:
    """Session a turn is stored in: the requested one, else the store's active one.

    Mirrors ``get_hierarchical_memory`` so every chat path (including @agent
    mentions) persists a brand-new chat's first turn.
    """
    if session_id:
        return session_id
    try:
        data = await asyncio.to_thread(load_sessions, root)
        return data.get("active_session_id")
    except Exception:
        return None


async def _tracked_chat_sse(entry: _ChatStreamEntry, inner):
    """Wrap a chat SSE body: announce the session, mirror the answer, honour Stop.

    Every frame is persisted under ``chat:<stream_id>`` with a monotonic event
    id, so a dropped connection can resume with ``Last-Event-ID`` via
    ``GET /api/streams/{stream_id}/events``.
    """
    stream_key = f"chat:{entry.stream_id}"
    try:
        session_event = {
            "type": "session",
            "id": entry.session_id,
            "stream_id": entry.stream_id,
        }
        stored = await event_hub.publish(stream_key, session_event)
        yield event_sse.format_event(stored)
        async for chunk in inner:
            # The generator has run past its user-message append once it yields.
            entry.started = True
            if entry.cancelled:
                break
            event = event_sse.parse_data(chunk)
            if event is not None:
                stored = await event_hub.publish(stream_key, event)
                chunk = event_sse.format_event(stored)
            entry.observe(chunk)
            yield chunk
        if entry.cancelled:
            # Stop already saved the partial answer; closing the generator runs
            # its ``finally`` now (its duplicate append is dropped by the store).
            aclose = getattr(inner, "aclose", None)
            if aclose is not None:
                try:
                    await aclose()
                except Exception:
                    pass
    finally:
        _unregister_chat_stream(entry)


@app.post("/api/chat/stop")
async def chat_stop(stream_id: str):
    """Stop a chat stream and persist its partial answer before responding.

    Idempotent. Response: ``{"status": "stopped" | "finished" | "not_found",
    "persisted": bool, "session_id": str | null}``. ``persisted`` is true when
    this call wrote the partial answer; the stream's own late save of the
    same turn is suppressed so the answer is stored exactly once.
    """
    from palimind.memory.session_store import persist_stopped_turn

    entry = _CHAT_STREAMS.get(stream_id)
    if entry is None:
        return {"status": "not_found", "persisted": False, "session_id": None}
    async with entry.stop_lock:
        if entry.stop_result is not None:
            return {**entry.stop_result, "persisted": False}
        entry.cancelled = True
        persisted = False
        status = "finished" if entry.finished else "stopped"
        if not entry.finished and entry.started and entry.root is not None and entry.session_id:
            try:
                persisted = await asyncio.to_thread(
                    persist_stopped_turn,
                    entry.root,
                    entry.session_id,
                    entry.text,
                    sources=entry.sources,
                    mode=entry.mode,
                    mode_params=entry.mode_params,
                    citations=entry.citations,
                )
            except Exception as exc:
                print(f"[chat] failed to save stopped turn: {exc}")
        entry.stop_result = {
            "status": status,
            "persisted": persisted,
            "session_id": entry.session_id,
        }
        return entry.stop_result


@app.get("/api/chat")
async def chat_stream(
    q: str,
    session_id: str | None = None,
    files: str | None = None,
    attachment_ids: str | None = None,
    chat_mode: str = "document",
    web_search: str = "true",
    llm_sub_mode: str | None = None,
    scope: str = "field",
    rerank: bool | None = None,
    stream_id: str | None = None,
):
    """Chat SSE stream.

    The first event is always ``{"type": "session", "id": <session id or
    null>, "stream_id": <id>}`` so the client knows which conversation the
    turn belongs to (a brand-new chat has no id client-side) and which id to
    pass to ``POST /api/chat/stop``. ``stream_id`` may be supplied by the
    client so Stop works even before that first event arrives.
    """
    entry = _register_chat_stream(stream_id)
    try:
        response = await _chat_stream_response(
            entry,
            q,
            session_id,
            files,
            attachment_ids,
            chat_mode,
            web_search,
            llm_sub_mode,
            scope,
            rerank,
        )
    except BaseException:
        _unregister_chat_stream(entry)
        raise
    response.body_iterator = _tracked_chat_sse(entry, response.body_iterator)
    return response


async def _chat_stream_response(
    entry: "_ChatStreamEntry",
    q: str,
    session_id: str | None,
    files: str | None,
    attachment_ids: str | None,
    chat_mode: str,
    web_search: str,
    llm_sub_mode: str | None,
    scope: str,
    rerank: bool | None,
) -> StreamingResponse:
    if scope.startswith("agent:"):
        return await _agent_scope_chat(scope, q, session_id, entry)

    root = _chat_root(scope)
    if root is None:

        async def err_stream():
            yield f"data: {json.dumps({'type': 'error', 'text': 'No active knowledge base'})}\n\n"

        return StreamingResponse(err_stream(), media_type="text/event-stream")

    is_global_chat = scope == "chat"
    if is_global_chat:
        # Global chat never queries documents — plain LLM only.
        chat_mode = "llm"
        config = _global_chat_config()
    else:
        from palimind.config import load_config

        config = load_config(root)
    from palimind.core.persona import persona_block

    ollama_url = config.get("ollama_base_url", "http://localhost:11434")
    chat_model = config.get("chat_model", "llama3")
    embed_model = config.get("embed_model", "bge-m3")
    persona = persona_block(root) if not is_global_chat else ""

    from palimind.uploads import build_attachment_context, resolve_attachments

    resolved_attachments = await asyncio.to_thread(resolve_attachments, attachment_ids)
    image_paths = list(resolved_attachments.get("image_paths") or [])
    attachment_context = build_attachment_context(resolved_attachments)

    # If the turn carries images and the selected chat model has no vision
    # capability, route it to the configured local vision model.
    if image_paths:
        from palimind.model_capabilities import infer_from_name

        if not infer_from_name(chat_model).supports_vision:
            vision_model = str(config.get("vision_model") or "llava")
            if vision_model:
                print(f"[chat] image turn: routing {chat_model!r} -> {vision_model!r}")
                chat_model = vision_model

    # ── @agent mention routing ────────────────────────────────────────
    # A mention routes the whole turn to that agent. It is recognized anywhere
    # in the message (not only at the start), so "summarise @researcher on X"
    # works, and the mention token is removed from the agent's input.
    mention = _AGENT_MENTION_RE.search(q)
    if mention:
        candidate = mention.group(2).strip()
        if candidate:
            from palimind.agents.registry import get_registry
            from palimind.agents.service import agent_sse_stream

            defn = get_registry().get(candidate)
            if defn is not None and defn.enabled:
                agent_input = (q[: mention.start()] + q[mention.end() :]).strip()
                if attachment_context:
                    agent_input = f"{agent_input}\n\n{attachment_context}".strip()
                mention_session = await _resolve_chat_session(root, session_id)
                entry.bind(
                    root, mention_session, mode="agent", mode_params={"agent_name": defn.name}
                )
                return await agent_sse_stream(
                    root,
                    defn.name,
                    agent_input or "Run your task.",
                    mention_session,
                    ollama_url,
                    chat_model,
                    working_root=root if not is_global_chat else None,
                    chat_style=True,
                )

    moe_sub_mode = (
        llm_sub_mode
        if (llm_sub_mode is not None and llm_sub_mode != "")
        else config.get("moe_sub_mode", "default")
    )
    long_term_limit = 0 if (chat_mode == "llm" and moe_sub_mode == "default") else 3

    from palimind.memory.hierarchical import get_hierarchical_memory

    mem = await asyncio.to_thread(
        get_hierarchical_memory,
        root,
        session_id,
        q,
        ollama_url,
        embed_model,
        5,
        long_term_limit,
    )

    active_sess_id = mem["active_sess_id"]
    entry.bind(root, active_sess_id)
    history_to_send = mem["short_term"]
    mid_term_summary = mem["mid_term_summary"]
    long_term_episodes = mem["long_term_episodes"]

    files_filter = None
    if files:
        files_filter = [f.strip() for f in files.split(",") if f.strip()]

    if chat_mode == "document":
        from palimind.opencode.router import resolve_model

        resolved_model, resolved_url, model_note = await asyncio.to_thread(
            resolve_model, chat_model, ollama_url, fallback_model=chat_model
        )
        if model_note:
            print(f"[chat] {model_note}")

        return await document_mode_stream(
            q,
            active_sess_id,
            history_to_send,
            mid_term_summary,
            files_filter,
            resolved_url,
            resolved_model,
            root,
            web_search,
            long_term_episodes=long_term_episodes,
            persona=persona,
            rerank=rerank,
            image_paths=image_paths,
            attachment_context=attachment_context,
        )

    moe_sub_mode = (
        llm_sub_mode
        if (llm_sub_mode is not None and llm_sub_mode != "")
        else config.get("moe_sub_mode", "default")
    )
    if chat_mode == "llm" and moe_sub_mode == "moe":
        from palimind.opencode.router import resolve_model

        orchestrator_model = config.get("moe_orchestrator_model", "") or chat_model
        worker_model = config.get("moe_worker_model", "") or chat_model
        # resolve_model does blocking HTTP (up to several seconds when a
        # backend is down); keep it off the event loop.
        orchestrator_model, orch_url, orch_note = await asyncio.to_thread(
            resolve_model, orchestrator_model, ollama_url, fallback_model=chat_model
        )
        worker_model, work_url, work_note = await asyncio.to_thread(
            resolve_model, worker_model, ollama_url, fallback_model=chat_model
        )
        for note in (orch_note, work_note):
            if note:
                print(f"[chat] {note}")
        return await moe_mode_stream(
            q,
            active_sess_id,
            history_to_send,
            mid_term_summary,
            files_filter,
            ollama_url,
            chat_model,
            root,
            web_search,
            orchestrator_model=orchestrator_model,
            worker_model=worker_model,
            orchestrator_url=orch_url,
            worker_url=work_url,
            long_term_episodes=long_term_episodes,
        )

    if chat_mode == "llm" and moe_sub_mode == "deep_research":
        from palimind.opencode.router import resolve_model

        dr_model = config.get("deep_research_model", "") or chat_model
        dr_model, dr_url, dr_note = await asyncio.to_thread(
            resolve_model, dr_model, ollama_url, fallback_model=chat_model
        )
        if dr_note:
            print(f"[chat] {dr_note}")
        return await deep_research_mode_stream(
            q,
            active_sess_id,
            history_to_send,
            mid_term_summary,
            files_filter,
            ollama_url,
            chat_model,
            root,
            web_search,
            orchestrator_model=dr_model,
            worker_model=dr_model,
            orchestrator_url=dr_url,
            worker_url=dr_url,
            long_term_episodes=long_term_episodes,
        )

    from palimind.opencode.router import resolve_model

    resolved_model, resolved_url, model_note = await asyncio.to_thread(
        resolve_model, chat_model, ollama_url, fallback_model=chat_model
    )
    if model_note:
        print(f"[chat] {model_note}")

    return await llm_mode_stream(
        q,
        active_sess_id,
        history_to_send,
        mid_term_summary,
        files_filter,
        resolved_url,
        resolved_model,
        root,
        web_search,
        long_term_episodes=long_term_episodes,
        persona=persona,
        image_paths=image_paths,
        attachment_context=attachment_context,
    )


@app.get("/api/setup/status")
async def setup_status_endpoint():
    """Active first-run model downloads / loads, for the UI progress banner."""
    from palimind import setup_status

    return {"tasks": setup_status.snapshot()}


# -- Model Switcher & Config Endpoints --


def _fetch_ollama_models_blocking(ollama_url: str) -> list[dict]:
    """Fetch available models from Ollama. Tries configured URL, then localhost fallback."""
    import urllib.error
    import urllib.request

    def _try_fetch(url: str) -> list[dict] | None:
        """Returns parsed model list or None on any failure."""
        try:
            req = urllib.request.Request(url, method="GET")
            req.add_header("User-Agent", "Palimind/2.0")
            req.add_header("bypass-tunnel-reminder", "lol")  # localtunnel bypass
            with urllib.request.urlopen(req, timeout=8) as resp:
                # localtunnel sometimes returns an HTML warning page
                ctype = resp.headers.get("Content-Type", "")
                if "html" in ctype:
                    return None  # not JSON — tunnel warning page
                data = json.loads(resp.read().decode("utf-8"))
                models = []
                for m in data.get("models", []):
                    name = m.get("name", "")
                    size_bytes = m.get("size", 0)
                    size_gb = round(size_bytes / (1024**3), 1) if size_bytes else 0
                    models.append(
                        {
                            "model_id": name,
                            "display_name": name,
                            "family": m.get("details", {}).get("family", ""),
                            "parameter_size": m.get("details", {}).get("parameter_size", ""),
                            "size_gb": size_gb,
                            "provider": "ollama",
                        }
                    )
                return models
        except Exception as e:
            print(f"[Models] fetch failed ({url}): {e}")
            return None

    base = ollama_url.rstrip("/")
    configured_result = _try_fetch(f"{base}/api/tags")
    if configured_result is not None:
        return configured_result

    # Fallback: try local Ollama if configured URL failed
    if "localhost" not in base and "127.0.0.1" not in base:
        local_result = _try_fetch("http://localhost:11434/api/tags")
        if local_result is not None:
            return local_result

    return []


# -- Settings: OpenCode API Key --

# Same upstream as palimind.opencode_proxy; env override kept in sync.
_OPENCODE_BASE_URL = _os.environ.get("OPENCODE_BASE_URL", "https://opencode.ai/zen/go/v1").rstrip(
    "/"
)

# Optional model used for the fallback completion probe. The primary check is
# the credential-scoped ``GET /models`` call: validating a key must not depend
# on any particular model remaining available (OpenCode retires free models
# regularly, which previously made valid keys fail with
# "400 Model is unavailable").
_OPENCODE_KEY_PROBE_MODEL = _os.environ.get("OPENCODE_KEY_PROBE_MODEL", "").strip()


async def _probe_opencode_key(key: str) -> tuple[bool, str]:
    """Verify *key* against OpenCode Zen without depending on a specific model.

    The credential is checked with ``GET /models`` (401/403 means rejected).
    If that endpoint is unavailable, fall back to a 1-token completion. A
    completion that fails only because the probe model is unavailable is
    treated as "the credential authenticated", not as a bad key.

    Returns ``(ok, reason)`` where ``reason`` is a short, user-facing
    explanation. Distinguishes an upstream 401 ("rejected") from transport
    problems ("could not reach") so the UI does not claim a key is invalid
    when the real problem is the network.
    """
    from palimind.opencode.session import SESSION_HEADER, opencode_session_id

    headers = {
        "Authorization": f"Bearer {key}",
        SESSION_HEADER: opencode_session_id(),
    }
    timeout = httpx.Timeout(connect=15.0, read=30.0, write=15.0, pool=15.0)
    models_status: int | None = None
    model_ids: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            models_resp = await client.get(f"{_OPENCODE_BASE_URL}/models", headers=headers)
            models_status = models_resp.status_code
            if models_resp.status_code in (401, 403):
                return False, "OpenCode rejected this key (401 Unauthorized)."
            if models_resp.status_code == 200:
                try:
                    body = models_resp.json()
                    model_ids = [
                        str(m.get("id"))
                        for m in (body.get("data") or [])
                        if isinstance(m, dict) and m.get("id")
                    ]
                except Exception:
                    model_ids = []
                # A 200 from this credential-scoped endpoint is sufficient proof.
                return True, ""

            # Some deployments expose chat but not /models. Probe with a model
            # that is actually listed, or the configured fallback.
            probe_model = _OPENCODE_KEY_PROBE_MODEL
            if not probe_model and model_ids:
                probe_model = model_ids[0]
            if probe_model:
                payload = {
                    "model": probe_model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                }
                resp = await client.post(
                    f"{_OPENCODE_BASE_URL}/chat/completions", json=payload, headers=headers
                )
                if resp.status_code in (401, 403):
                    return False, "OpenCode rejected this key (401 Unauthorized)."
                if resp.status_code < 400:
                    return True, ""
                detail = ""
                try:
                    detail = (resp.json().get("error") or {}).get("message", "")
                except Exception:
                    pass
                # Auth succeeded but the probe model is retired/unavailable.
                if resp.status_code == 400 and "model" in detail.lower():
                    return True, ""
                suffix = f": {detail}" if detail else ""
                return False, f"OpenCode returned HTTP {resp.status_code}{suffix}"
    except Exception:
        return False, "Could not reach OpenCode — check your network connection."

    if models_status is not None and models_status >= 400:
        return False, f"OpenCode returned HTTP {models_status} while checking the key."
    return True, ""


@app.get("/api/settings/opencode-key")
async def get_opencode_key():
    """Report whether an OpenCode API key is stored globally.

    Never returns the raw key — only a masked preview fragment. A broken
    global auth store (unreadable file, invalid/non-object JSON) is reported
    via ``error`` instead of surfacing as a 500.
    """
    from palimind.opencode.auth import get_key, masked_preview

    try:
        key = get_key()
    except (OSError, ValueError):
        return {"configured": False, "masked": None, "error": "Failed to read API key"}
    if not key:
        return {"configured": False, "masked": None}
    return {"configured": True, "masked": masked_preview(key)}


@app.post("/api/settings/opencode-key")
async def save_opencode_key(req: Request):
    """Validate an OpenCode Zen API key against upstream, then store it globally."""
    from palimind.opencode.auth import set_key

    data = await req.json()
    key = str(data.get("key") or "").strip()
    if len(key) < 10:
        return {"error": "Invalid API key: must be at least 10 characters"}
    # Reject obvious non-credentials early. Keys are opaque tokens, but real
    # ones never contain whitespace or sentence punctuation; catching this here
    # avoids a pointless round-trip and gives a clearer message than a 401.
    if any(c.isspace() for c in key):
        return {"error": "That does not look like an API key — it contains spaces."}

    ok, reason = await _probe_opencode_key(key)
    if not ok:
        return {"error": reason}

    try:
        set_key(key)
    except (ValueError, OSError) as e:
        return {"error": f"Key is valid but could not be saved: {e}"}

    # Drop any model list cached while the key was missing/invalid so the new
    # key takes effect on the very next request.
    try:
        from palimind.opencode.router import reset_cache

        reset_cache()
    except Exception:
        pass
    return {"status": "success"}


@app.delete("/api/settings/opencode-key")
async def delete_opencode_key():
    """Remove the stored OpenCode API key from the global auth file."""
    from palimind.opencode.auth import remove_key

    try:
        remove_key()
    except (ValueError, OSError):
        return {"error": "Failed to remove API key"}
    try:
        from palimind.opencode.router import reset_cache

        reset_cache()
    except Exception:
        pass
    return {"status": "success"}


# -- Settings: Voice / Speech-to-text --

VOICE_STT_OPTIONS = [
    {
        "id": "tiny.en",
        "label": "Tiny (English)",
        "size_mb": 75,
        "note": "Fastest, least accurate",
    },
    {
        "id": "base.en",
        "label": "Base (English)",
        "size_mb": 145,
        "note": "Recommended default for CPU",
    },
    {
        "id": "small.en",
        "label": "Small (English)",
        "size_mb": 480,
        "note": "More accurate, slower on CPU",
    },
    {
        "id": "distil-small.en",
        "label": "Distil Small (English)",
        "size_mb": 330,
        "note": "Fast and accurate (English)",
    },
    {
        "id": "small",
        "label": "Small (multilingual)",
        "size_mb": 480,
        "note": "For non-English dictation",
    },
    {
        "id": "medium",
        "label": "Medium (multilingual)",
        "size_mb": 1500,
        "note": "Slower on CPU",
    },
    {
        "id": "large-v3",
        "label": "Large v3 (multilingual)",
        "size_mb": 3100,
        "note": "Best accuracy; needs a GPU",
    },
]


@app.get("/api/settings/voice")
async def get_voice_settings():
    """Return the configured microphone STT model and the selectable options."""
    from palimind.audio.stt import resolve_model_name

    return {"stt_whisper_model": resolve_model_name(), "options": VOICE_STT_OPTIONS}


@app.patch("/api/settings/voice")
async def update_voice_settings(req: Request):
    """Persist the microphone STT model to the global config."""
    data = await req.json()
    model = str(data.get("stt_whisper_model", "")).strip()
    if not model:
        return {"error": "stt_whisper_model is required"}
    try:
        global_data: dict = {}
        if GLOBAL_CONFIG_PATH.exists():
            global_data = json.loads(GLOBAL_CONFIG_PATH.read_text("utf-8"))
        global_data["stt_whisper_model"] = model
        _write_global_config(global_data)
    except Exception:
        return {"error": "Failed to update voice settings"}
    return {"status": "success", "stt_whisper_model": model}


def run_server(port: int = 8000, host: str | None = None):
    _detach_stdio()
    if host is None:
        from palimind.settings import SERVER_HOST

        host = SERVER_HOST
    uvicorn.run("palimind.api_server:app", host=host, port=port)


if __name__ == "__main__":
    import argparse

    from palimind.settings import SERVER_HOST

    parser = argparse.ArgumentParser(description="Palimind API server")
    parser.add_argument("--host", default=SERVER_HOST)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)
