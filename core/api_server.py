import asyncio
import json
import os as _os
import platform
import subprocess
import sys as _sys
import tkinter as tk
import uuid
import time
from tkinter import filedialog
from pathlib import Path
from typing import AsyncGenerator, Any


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
            _os.dup2(devnull_fd, 1)   # stdout → /dev/null
            _os.dup2(devnull_fd, 2)   # stderr → /dev/null
        finally:
            _os.close(devnull_fd)
        # Also redirect the Python-level objects so sys.stdout.write() is safe
        _sys.stdout = open(_os.devnull, "w", encoding="utf-8")
        _sys.stderr = open(_os.devnull, "w", encoding="utf-8")
    except Exception:
        pass  # never crash the server over a logging redirect


from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
import uvicorn

from core.api import (
    initialize_index,
    update_index,
    query_stream,
    require_index,
    IndexNotFoundError,
    PalimindError,
)
from core.audio_stt import transcribe_wav_bytes
from core.audio_tts import text_to_speech_bytes
from core.session_store import (
    load_sessions,
    save_sessions,
    add_new_session,
    set_active_session_id,
    delete_session,
    append_message_to_session,
    background_update_memory,
)
from core.document.stream import document_mode_stream
from core.llm.stream import llm_mode_stream, moe_mode_stream
from core.palivision_router import router as palivision_router
from core.agents.api import router as agents_router


app = FastAPI(title="Palimind V2 API")


app = FastAPI(title="Palimind V2 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(palivision_router)
app.include_router(agents_router)



UI_DIR = Path(__file__).parent.parent / "frontend" / "dist"


class SPAStaticFiles(StaticFiles):
    """Serve index.html for unknown paths so the SPA can route client-side."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException:
            pass
        # File/dir not found → fall back to the SPA entry point
        try:
            return await super().get_response("index.html", scope)
        except Exception:
            raise


if UI_DIR.exists():
    @app.get("/ui/glance", response_class=HTMLResponse)
    async def serve_glance():
        glance_file = UI_DIR / "glance.html"
        return glance_file.read_text("utf-8")

    app.mount("/ui", SPAStaticFiles(directory=UI_DIR, html=True), name="ui")



# -- Global State & Config --
GLOBAL_CONFIG_PATH = Path.home() / ".palimind_global.json"

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
        GLOBAL_CONFIG_PATH.write_text(
            json.dumps({
                "fields": self.fields,
                "active_field": str(self.active_field) if self.active_field else None
            }, indent=2),
            "utf-8"
        )

state = AppState()
state.load()

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
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
    except Exception:
        pass
    return ""

# -- Global Event Listeners for Watcher notifications --
EVENT_LISTENERS = set()

async def broadcast_event(data: dict):
    for queue in list(EVENT_LISTENERS):
        await queue.put(data)

async def background_index_field(path: Path):
    state.is_indexing = True
    state.indexing_status = f"Indexing [{path.name}]..."
    await broadcast_event({
        "type": "indexing_start",
        "message": state.indexing_status
    })
    
    try:
        # Require or initialize index
        try:
            await asyncio.to_thread(require_index, path)
        except IndexNotFoundError:
            await asyncio.to_thread(initialize_index, path)
            
        await asyncio.to_thread(update_index, path)
        update_watcher(path)
        
        try:
            from core.config import load_config
            cfg = load_config(path)
            ollama_url = cfg.get("ollama_base_url", "http://localhost:11434")
            from core.document.graph import build_doc_graph
            await asyncio.to_thread(build_doc_graph, path, ollama_url)
        except Exception as e:
            print(f"Background graph build failed: {e}")
        
        state.is_indexing = False
        state.indexing_status = ""
        await broadcast_event({
            "type": "indexing_complete",
            "message": f"[{path.name}] indexed successfully!"
        })
        await broadcast_event({
            "type": "sync",
            "message": f"[{path.name}] Context Updated"
        })
    except Exception as e:
        state.is_indexing = False
        state.indexing_status = ""
        await broadcast_event({
            "type": "indexing_error",
            "message": f"Failed to index [{path.name}]: {str(e)}"
        })

def handle_watcher_change(root: Path):
    print(f"Watcher: detected file changes in {root}. Syncing index...")
    try:
        # Write debug file to verify execution
        debug_path = root / ".palimind" / "watcher_debug.txt"
        debug_path.write_text(f"Watcher ran at {time.time()}", "utf-8")
        
        result = update_index(root)
        print(f"Watcher: index updated successfully.")
        if state.loop:
            asyncio.run_coroutine_threadsafe(
                broadcast_event({
                    "type": "sync",
                    "message": f"[{root.name}] Context Updated",
                    "indexed": result.indexed_files,
                    "deleted": result.deleted_files
                }),
                state.loop
            )
    except Exception as e:
        print(f"Watcher: index update failed: {e}")

def update_watcher(path: Path | None):
    # Watcher is disabled. Syncing only occurs when user manually triggers it.
    pass


def _add_capture_to_field(root: Path, text: str) -> dict:
    """Index a captured text snippet into a field's vector DB and rebuild the knowledge graph."""
    from core.config import load_config
    from core.embedder import generate_embedding
    from core.storage.vector_store import VectorStore
    from core.storage.db import get_connection, upsert_file, insert_chunks
    from core.document.graph import build_doc_graph

    config = load_config(root)

    # Generate embedding
    embedding = generate_embedding(
        text, config["ollama_base_url"], config["embed_model"], root
    )
    if not embedding:
        return {"error": "Failed to generate embedding"}

    capture_id = str(uuid.uuid4())[:8]
    capture_path = f"_captures_/{capture_id}.md"

    conn = get_connection(root)
    try:
        file_id = upsert_file(conn, capture_path, capture_id, time.time())

        chunk_db_ids = insert_chunks(conn, file_id, [
            (0, "capture", text, "Capture", "", "", None, None, None),
        ])

        # Insert into vector store
        with VectorStore(root) as vstore:
            vstore.insert([{
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
            }])

        conn.commit()
    finally:
        conn.close()

    # Rebuild knowledge graph in background
    try:
        graph = build_doc_graph(root, config["ollama_base_url"])
    except Exception as e:
        print(f"[capture] graph rebuild failed: {e}")

    return {"status": "success", "capture_id": capture_id}


def build_file_tree(root: Path) -> list[dict]:
    def walk(path: Path) -> list[dict]:
        items = []
        try:
            for entry in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                if entry.name in [".palimind", ".git", "node_modules", "__pycache__", ".venv", "venv", ".idea", ".vscode"]:
                    continue
                if entry.name.startswith("."):
                    continue
                
                rel_path = str(entry.relative_to(root))
                if entry.is_dir():
                    children = walk(entry)
                    items.append({
                        "name": entry.name,
                        "path": rel_path,
                        "type": "directory",
                        "children": children
                    })
                else:
                    items.append({
                        "name": entry.name,
                        "path": rel_path,
                        "type": "file"
                    })
        except Exception:
            pass
        return items
    return walk(root)
@app.on_event("startup")
async def startup_event():
    state.loop = asyncio.get_running_loop()

    from core.agents.registry import set_registry_field
    from core.agents.scheduler import start_scheduler, stop_scheduler

    set_registry_field(state.active_field)
    start_scheduler(state.loop)

    if state.active_field:
        update_watcher(state.active_field)


@app.on_event("shutdown")
async def shutdown_event():
    from core.agents.scheduler import stop_scheduler

    stop_scheduler()
    if state.watcher:
        try:
            state.watcher.stop()
        except Exception:
            pass


def _on_field_changed(field: Path | None) -> None:
    """Repoint the agent registry at the active field (no-op before startup)."""
    try:
        import asyncio as _aio

        from core.agents.registry import set_registry_field

        if _aio.get_running_loop() is not None:
            set_registry_field(field)
    except RuntimeError:
        pass

# -- Endpoints --

# ── Hotkey capture endpoints ────────────────────────────────────────────

@app.get("/")
async def health_check():
    """Root health check used by helper scripts."""
    return {"status": "ok", "app": "Palimind"}


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
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": f"Failed to save capture: {str(e)}"}


@app.get("/api/fields")
async def get_fields():
    return {
        "fields": state.fields,
        "active_field": str(state.active_field) if state.active_field else None,
        "is_indexing": state.is_indexing,
        "indexing_status": state.indexing_status
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
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=180
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
        
    current_path = str(target_path)
    parent_path = str(target_path.parent) if target_path.parent != target_path else None
    
    items = []
    try:
        for entry in sorted(target_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            # Hide hidden files/folders by default
            if entry.name.startswith("."):
                continue
            items.append({
                "name": entry.name,
                "path": str(entry.resolve()),
                "type": "directory" if entry.is_dir() else "file"
            })
    except Exception as e:
        return {"error": f"Failed to list directory: {str(e)}"}
        
    return {
        "current_path": current_path,
        "parent_path": parent_path,
        "items": items
    }

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
        
        # Fire and forget graph build so we don't block the UI
        async def _build_graph():
            try:
                from core.config import load_config
                cfg = load_config(state.active_field)
                ollama_url = cfg.get("ollama_base_url", "http://localhost:11434")
                from core.document.graph import build_doc_graph
                await asyncio.to_thread(build_doc_graph, state.active_field, ollama_url)
            except Exception as e:
                print(f"Background graph build failed: {e}")
                
        asyncio.create_task(_build_graph())
        
        return {
            "status": "success",
            "indexed_files": result.indexed_files,
            "deleted_files": result.deleted_files
        }
    except Exception as e:
        return {"error": str(e)}

# -- Endpoints --

@app.get("/api/sessions")
async def get_sessions():
    if not state.active_field:
        return {"error": "No active field"}
    sessions_data = await asyncio.to_thread(load_sessions, state.active_field)
    return sessions_data

@app.post("/api/sessions/new")
async def create_session(req: Request):
    if not state.active_field:
        return {"error": "No active field"}
    data = await req.json()
    name = data.get("name", "New Session")
    sessions_data = await asyncio.to_thread(add_new_session, state.active_field, name)
    return sessions_data

@app.post("/api/sessions/set_active")
async def set_active_session(req: Request):
    if not state.active_field:
        return {"error": "No active field"}
    data = await req.json()
    session_id = data.get("session_id")
    if not session_id:
        return {"error": "session_id is required"}
    sessions_data = await asyncio.to_thread(set_active_session_id, state.active_field, session_id)
    return sessions_data

@app.post("/api/sessions/remove")
async def remove_session(req: Request):
    if not state.active_field:
        return {"error": "No active field"}
    data = await req.json()
    session_id = data.get("session_id")
    if not session_id:
        return {"error": "session_id is required"}
    sessions_data = await asyncio.to_thread(delete_session, state.active_field, session_id)
    return sessions_data

@app.get("/api/events")
async def events_stream():
    queue = asyncio.Queue()
    EVENT_LISTENERS.add(queue)
    
    async def generator():
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            EVENT_LISTENERS.remove(queue)
            
    return StreamingResponse(generator(), media_type="text/event-stream")

@app.get("/api/files/tree")
async def get_files_tree():
    if not state.active_field:
        return {"error": "No active field"}
    tree = await asyncio.to_thread(build_file_tree, state.active_field)
    return {"tree": tree}

def list_directory_shallow(root: Path, subpath: str) -> list[dict]:
    target = root / subpath if subpath else root
    items = []
    try:
        for entry in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if entry.name in [".palimind", ".git", "node_modules", "__pycache__", ".venv", "venv", ".idea", ".vscode"]:
                continue
            if entry.name.startswith("."):
                continue
            items.append({
                "name": entry.name,
                "path": str(entry.relative_to(root)),
                "type": "directory" if entry.is_dir() else "file"
            })
    except Exception:
        pass
    return items

@app.get("/api/files/tree/sub")
async def get_file_tree_sub(path: str = ""):
    if not state.active_field:
        return {"error": "No active field"}
    children = await asyncio.to_thread(list_directory_shallow, state.active_field, path)
    return {"children": children}

@app.get("/api/chat")
async def chat_stream(q: str, session_id: str | None = None, files: str | None = None, chat_mode: str = "document", web_search: str = "false", llm_sub_mode: str | None = None, think: str = "false"):
    if not state.active_field:
        async def err_stream():
            yield f"data: {json.dumps({'type': 'error', 'text': 'No active field'})}\n\n"
        return StreamingResponse(err_stream(), media_type="text/event-stream")

    from core.config import load_config
    from core.persona import persona_block
    config = load_config(state.active_field)
    ollama_url = config.get("ollama_base_url", "http://localhost:11434")
    chat_model = config.get("chat_model", "llama3")
    embed_model = config.get("embed_model", "nomic-embed-text")
    if str(think).lower() in ("1", "true", "yes"):
        chat_model = config.get("thinking_model", "") or chat_model
    persona = persona_block(state.active_field)

    # ── @agent mention routing ────────────────────────────────────────
    stripped_q = q.lstrip()
    if stripped_q.startswith("@"):
        mention_parts = stripped_q[1:].split(None, 1)
        candidate = mention_parts[0].strip() if mention_parts else ""
        if candidate:
            from core.agents.registry import get_registry
            from core.agents.stream import agent_mode_stream

            defn = get_registry().get(candidate)
            if defn is not None and defn.enabled:
                agent_input = mention_parts[1].strip() if len(mention_parts) > 1 else ""
                return await agent_mode_stream(
                    state.active_field,
                    defn.name,
                    agent_input or "Run your task.",
                    session_id,
                    ollama_url,
                    chat_model,
                )

    moe_sub_mode = llm_sub_mode if (llm_sub_mode is not None and llm_sub_mode != "") else config.get("moe_sub_mode", "default")
    long_term_limit = 0 if (chat_mode == "llm" and moe_sub_mode != "moe") else 3

    from core.memory import get_hierarchical_memory
    mem = await asyncio.to_thread(
        get_hierarchical_memory,
        state.active_field,
        session_id,
        q,
        ollama_url,
        embed_model,
        5,
        long_term_limit,
    )

    active_sess_id = mem["active_sess_id"]
    history_to_send = mem["short_term"]
    mid_term_summary = mem["mid_term_summary"]
    long_term_episodes = mem["long_term_episodes"]

    files_filter = None
    if files:
        files_filter = [f.strip() for f in files.split(",") if f.strip()]

    if chat_mode == "document":
        return await document_mode_stream(
            q, active_sess_id, history_to_send, mid_term_summary, files_filter,
            ollama_url, chat_model, state.active_field, web_search,
            long_term_episodes=long_term_episodes,
            persona=persona,
        )

    moe_sub_mode = llm_sub_mode if (llm_sub_mode is not None and llm_sub_mode != "") else config.get("moe_sub_mode", "default")
    if chat_mode == "llm" and moe_sub_mode == "moe":
        orchestrator_model = config.get("moe_orchestrator_model", "") or chat_model
        worker_model = config.get("moe_worker_model", "") or chat_model
        return await moe_mode_stream(
            q, active_sess_id, history_to_send, mid_term_summary,
            files_filter, ollama_url, chat_model, state.active_field, web_search,
            orchestrator_model=orchestrator_model, worker_model=worker_model,
            long_term_episodes=long_term_episodes,
        )

    return await llm_mode_stream(
        q, active_sess_id, history_to_send, mid_term_summary, files_filter,
        ollama_url, chat_model, state.active_field, web_search,
        long_term_episodes=long_term_episodes,
        persona=persona,
    )

_VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}

def _resolve_media_path(path_str: str) -> Path:
    """Resolve a media path against the active field and ensure it's inside it."""
    if not state.active_field:
        raise StarletteHTTPException(status_code=404, detail="No active field")
    root = state.active_field.resolve()
    candidate = Path(path_str)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if root != resolved and root not in resolved.parents:
        raise StarletteHTTPException(status_code=403, detail="Path outside workspace")
    return resolved

@app.get("/api/media/info")
async def media_info(path: str):
    """Return content type + size for a workspace media file."""
    try:
        resolved = _resolve_media_path(path)
    except StarletteHTTPException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Media file not found")
    import mimetypes

    mime = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    return {"size": resolved.stat().st_size, "mime": mime}

@app.get("/api/media/stream")
async def media_stream(request: Request, path: str):
    """Stream a local video/audio file from the active workspace with HTTP
    range support so the frontend player can seek."""
    from urllib.parse import unquote

    try:
        resolved = _resolve_media_path(unquote(path))
    except StarletteHTTPException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e
    if not resolved.is_file() or resolved.suffix.lower() not in _VIDEO_EXTS | {
        ".mp3", ".wav", ".m4a", ".flac", ".ogg",
    }:
        raise HTTPException(status_code=404, detail="Media file not found")

    import mimetypes
    import os

    mime = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    file_size = resolved.stat().st_size
    range_header = request.headers.get("range")

    if range_header:
        range_val = range_header.strip().lower()
        if range_val.startswith("bytes="):
            parts = range_val[6:].split("-", 1)
            start = int(parts[0]) if parts[0].isdigit() else 0
            end = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else min(
                start + 4 * 1024 * 1024 - 1, file_size - 1
            )
            end = min(end, file_size - 1)
            content_len = end - start + 1

            async def _range_gen():
                with resolved.open("rb") as f:
                    f.seek(start)
                    remaining = content_len
                    while remaining > 0:
                        chunk = f.read(min(1024 * 256, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        yield chunk

            return StreamingResponse(
                _range_gen(),
                status_code=206,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(content_len),
                    "Content-Type": mime,
                },
            )

    def _full_gen():
        with resolved.open("rb") as f:
            while True:
                chunk = f.read(1024 * 512)
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(
        _full_gen(),
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
            "Content-Type": mime,
        },
    )

@app.post("/api/voice/transcribe")
async def voice_transcribe(request: Request):
    wav_bytes = await request.body()
    if not wav_bytes:
        return {"error": "Empty audio data"}
    try:
        text = await asyncio.to_thread(transcribe_wav_bytes, wav_bytes)
        return {"text": text}
    except Exception as e:
        return {"error": f"Transcription failed: {str(e)}"}

@app.post("/api/voice/synthesize")
async def voice_synthesize(request: Request):
    try:
        data = await request.json()
        text = data.get("text")
        voice = data.get("voice", "af_bella")
        if not text:
            return Response(status_code=400, content="Text is required")
        
        wav_bytes = await asyncio.to_thread(text_to_speech_bytes, text, voice)
        if not wav_bytes:
            return Response(status_code=500, content="TTS synthesis failed")
            
        return Response(content=wav_bytes, media_type="audio/wav")
    except Exception as e:
        return Response(status_code=500, content=f"Synthesis error: {str(e)}")


# -- Model Switcher & Config Endpoints --

def _fetch_ollama_models_blocking(ollama_url: str) -> list[dict]:
    """Fetch available models from Ollama. Tries configured URL, then localhost fallback."""
    import urllib.request
    import urllib.error

    def _try_fetch(url: str) -> list[dict] | None:
        """Returns parsed model list or None on any failure."""
        try:
            req = urllib.request.Request(url, method="GET")
            req.add_header("User-Agent", "Palimind/2.0")
            req.add_header("bypass-tunnel-reminder", "lol")   # localtunnel bypass
            with urllib.request.urlopen(req, timeout=8) as resp:
                # localtunnel sometimes returns an HTML warning page
                ctype = resp.headers.get("Content-Type", "")
                if "html" in ctype:
                    return None   # not JSON — tunnel warning page
                data = json.loads(resp.read().decode("utf-8"))
                models = []
                for m in data.get("models", []):
                    name = m.get("name", "")
                    size_bytes = m.get("size", 0)
                    size_gb = round(size_bytes / (1024 ** 3), 1) if size_bytes else 0
                    models.append({
                        "model_id": name,
                        "display_name": name,
                        "family": m.get("details", {}).get("family", ""),
                        "parameter_size": m.get("details", {}).get("parameter_size", ""),
                        "size_gb": size_gb,
                        "provider": "ollama",
                    })
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


@app.get("/api/models")
async def get_models():
    """Fetch available models from configured Ollama instance."""
    from core.config import load_config
    config = {}
    if state.active_field:
        config = load_config(state.active_field)
    ollama_url = config.get("ollama_base_url", "http://localhost:11434")
    current_model = config.get("chat_model", "gemma4:e2b")
    try:
        models = await asyncio.to_thread(_fetch_ollama_models_blocking, ollama_url)
        return {
            "models": models,
            "current_model": current_model,
            "ollama_url": ollama_url,
            "status": "ok" if models else "empty",
        }
    except Exception as e:
        return {
            "error": str(e),
            "models": [],
            "current_model": current_model,
            "status": "offline",
        }


@app.patch("/api/config/model")
async def update_model(req: Request):
    """Update the active chat model for the current field."""
    data = await req.json()
    model_id = data.get("model_id")
    if not model_id:
        return {"error": "model_id is required"}

    from core.config import load_config, config_path, palimind_dir

    # Update field-level config
    if state.active_field:
        cfg = load_config(state.active_field)
        cfg["chat_model"] = model_id
        p_dir = palimind_dir(state.active_field)
        p_dir.mkdir(parents=True, exist_ok=True)
        cp = config_path(state.active_field)
        cp.write_text(json.dumps(cfg, indent=2), "utf-8")

    # Also update global config
    try:
        global_data = {}
        if GLOBAL_CONFIG_PATH.exists():
            global_data = json.loads(GLOBAL_CONFIG_PATH.read_text("utf-8"))
        global_data["chat_model"] = model_id
        GLOBAL_CONFIG_PATH.write_text(json.dumps(global_data, indent=2), "utf-8")
    except Exception:
        pass

    return {"status": "success", "model": model_id}


@app.get("/api/document/graph")
async def get_document_graph():
    """Return the document knowledge graph for the active field."""
    if not state.active_field:
        return {"error": "No active field", "nodes": [], "edges": []}
    try:
        from core.document.graph import load_doc_graph
        from core.config import load_config as _lc
        cfg = _lc(state.active_field)
        ollama_url = cfg.get("ollama_base_url", "http://localhost:11434")
        graph = await asyncio.to_thread(load_doc_graph, state.active_field, ollama_url, force_rebuild=False)
        # If loaded graph has no nodes but index exists, force rebuild
        if len(graph.nodes) == 0:
            from core.storage.db import get_connection, get_all_files
            try:
                conn = get_connection(state.active_field)
                files = get_all_files(conn)
                conn.close()
                if files:
                    print(f"[graph] empty graph but {len(files)} files indexed — forcing rebuild")
                    graph = await asyncio.to_thread(load_doc_graph, state.active_field, ollama_url, force_rebuild=True)
            except Exception as check_err:
                print(f"[graph] check error: {check_err}")
        nodes = []
        for nid, ndata in graph.nodes.items():
            nodes.append({
                "id": nid,
                "type": ndata.get("type", "unknown"),
                "label": ndata.get("label", nid),
                "file_path": ndata.get("file_path", ""),
            })
        edges = [
            {"source": e["source"], "target": e["target"], "relation": e["relation"]}
            for e in graph.edges
        ]
        return {
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "indexed_files": len(graph.file_nodes),
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e), "nodes": [], "edges": []}


@app.post("/api/document/graph/rebuild")
async def rebuild_document_graph():
    """Force rebuild the knowledge graph."""
    if not state.active_field:
        return {"error": "No active field"}
    try:
        from core.document.graph import build_doc_graph
        from core.config import load_config as _lc
        cfg = _lc(state.active_field)
        ollama_url = cfg.get("ollama_base_url", "http://localhost:11434")
        graph = await asyncio.to_thread(build_doc_graph, state.active_field, ollama_url)
        return {
            "status": "success",
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
            "indexed_files": len(graph.file_nodes),
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e)}


@app.get("/api/config")
async def get_config():
    """Return current config for the active field."""
    from core.config import load_config
    config = {}
    if state.active_field:
        config = load_config(state.active_field)
    return {
        "chat_model": config.get("chat_model", "llama3"),
        "embed_model": config.get("embed_model", "nomic-embed-text"),
        "ollama_base_url": config.get("ollama_base_url", "http://localhost:11434"),
        "moe_orchestrator_model": config.get("moe_orchestrator_model", ""),
        "moe_worker_model": config.get("moe_worker_model", ""),
        "moe_sub_mode": config.get("moe_sub_mode", "default"),
        "thinking_model": config.get("thinking_model", ""),
        "persona_name": config.get("persona_name", ""),
        "persona_system_prompt": config.get("persona_system_prompt", ""),
    }


def _patch_field_config(data: dict) -> None:
    from core.config import load_config, config_path, palimind_dir

    if not state.active_field:
        return
    cfg = load_config(state.active_field)
    cfg.update(data)
    p_dir = palimind_dir(state.active_field)
    p_dir.mkdir(parents=True, exist_ok=True)
    cp = config_path(state.active_field)
    cp.write_text(json.dumps(cfg, indent=2), "utf-8")


@app.patch("/api/config/persona")
async def update_persona(req: Request):
    """Set the per-field persona (name + system prompt). Empty prompt disables."""
    data = await req.json()
    patch = {}
    if "persona_name" in data:
        patch["persona_name"] = str(data["persona_name"]).strip()
    if "persona_system_prompt" in data:
        patch["persona_system_prompt"] = str(data["persona_system_prompt"])
    _patch_field_config(patch)
    return {"status": "success", **patch}


@app.patch("/api/config/thinking")
async def update_thinking(req: Request):
    """Set the model used by the Think toggle (falls back to chat_model when empty)."""
    data = await req.json()
    if "thinking_model" not in data:
        return {"error": "thinking_model is required"}
    thinking_model = str(data["thinking_model"])
    _patch_field_config({"thinking_model": thinking_model})
    try:
        global_data = {}
        if GLOBAL_CONFIG_PATH.exists():
            global_data = json.loads(GLOBAL_CONFIG_PATH.read_text("utf-8"))
        global_data["thinking_model"] = thinking_model
        GLOBAL_CONFIG_PATH.write_text(json.dumps(global_data, indent=2), "utf-8")
    except Exception:
        pass
    return {"status": "success", "thinking_model": thinking_model}


@app.patch("/api/config/moe")
async def update_moe_config(req: Request):
    """Update MoE configuration for the active field."""
    data = await req.json()
    from core.config import load_config, config_path, palimind_dir
    if state.active_field:
        cfg = load_config(state.active_field)
        if "moe_orchestrator_model" in data:
            cfg["moe_orchestrator_model"] = data["moe_orchestrator_model"]
        if "moe_worker_model" in data:
            cfg["moe_worker_model"] = data["moe_worker_model"]
        if "moe_sub_mode" in data:
            cfg["moe_sub_mode"] = data["moe_sub_mode"]
        p_dir = palimind_dir(state.active_field)
        p_dir.mkdir(parents=True, exist_ok=True)
        cp = config_path(state.active_field)
        cp.write_text(json.dumps(cfg, indent=2), "utf-8")
    return {"status": "success"}


@app.get("/api/moe/hardware-check")
async def moe_hardware_check():
    """Check hardware constraints for current MoE config."""
    from core.config import load_config
    from core.llm.mixture_of_expert import estimate_hardware_requirements
    from core.hwfit.hardware import detect_hardware
    config = {}
    if state.active_field:
        config = load_config(state.active_field)
    orch = config.get("moe_orchestrator_model", "") or config.get("chat_model", "llama3")
    worker = config.get("moe_worker_model", "") or config.get("chat_model", "llama3")
    try:
        hw = await asyncio.to_thread(detect_hardware)
        gpu_vram = max((g.vram_mb for g in hw.gpus), default=0)
        sys_ram = hw.total_ram_mb
        estimate = estimate_hardware_requirements(orch, worker, num_workers=4, gpu_vram_mb=gpu_vram, system_ram_mb=sys_ram)
        return {
            "fits_gpu": estimate.fits_gpu,
            "fits_ram": estimate.fits_ram,
            "vram_per_worker_mb": estimate.vram_per_worker_mb,
            "vram_orchestrator_mb": estimate.vram_orchestrator_mb,
            "total_vram_needed_mb": estimate.total_vram_needed_mb,
            "total_ram_needed_mb": estimate.total_ram_needed_mb,
            "suggested_worker": estimate.suggested_worker,
            "suggested_orchestrator": estimate.suggested_orchestrator,
            "gpu_vram_mb": gpu_vram,
            "system_ram_mb": sys_ram,
        }
    except Exception as e:
        return {"error": str(e)}


# -- Cookbook / Hardware Endpoints --

@app.get("/api/cookbook/hardware")
async def get_hardware():
    """Detect and return hardware profile for cookbook recommendations."""
    try:
        from core.hwfit.hardware import detect_hardware
        profile = await asyncio.to_thread(detect_hardware)
        return profile.to_dict()
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/cookbook/recommendations")
async def get_recommendations(top: int = 20):
    """Get hardware-aware model recommendations."""
    try:
        from core.hwfit.hardware import detect_hardware
        from core.hwfit.catalog import MODEL_CATALOG
        from core.hwfit.fit import rank_models
        profile = await asyncio.to_thread(detect_hardware)
        ranked = rank_models(profile, MODEL_CATALOG, top=top)
        return {"recommendations": ranked, "hardware": profile.to_dict()}
    except Exception as e:
        return {"error": str(e), "recommendations": []}


def run_server(port: int = 8000):
    _detach_stdio()
    uvicorn.run("core.api_server:app", host="127.0.0.1", port=port)

if __name__ == "__main__":
    _detach_stdio()
    run_server()
