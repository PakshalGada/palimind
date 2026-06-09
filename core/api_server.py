import asyncio
import json
import tkinter as tk
import uuid
import time
from tkinter import filedialog
from pathlib import Path
from typing import AsyncGenerator, Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
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

app = FastAPI(title="Palimind V2 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UI_DIR = Path(__file__).parent.parent / "ui"
if UI_DIR.exists():
    app.mount("/ui", StaticFiles(directory=UI_DIR, html=True), name="ui")

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
    if state.watcher:
        try:
            state.watcher.stop()
        except Exception:
            pass
        state.watcher = None
    
    if path:
        from core.watcher import FieldWatcher
        try:
            state.watcher = FieldWatcher(path, handle_watcher_change)
            state.watcher.start()
            print(f"Watcher started for field: {path}")
        except Exception as e:
            print(f"Failed to start watcher: {e}")

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
    if state.active_field:
        update_watcher(state.active_field)

@app.on_event("shutdown")
async def shutdown_event():
    if state.watcher:
        try:
            state.watcher.stop()
        except Exception:
            pass

# -- Endpoints --

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
    if path_key not in state.fields:
        state.fields.append(path_key)
    
    state.active_field = path
    state.save()

    # Start background indexing task
    asyncio.create_task(background_index_field(path))
    return {"status": "indexing", "field": path_key}

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
    
    # Start background indexing task
    asyncio.create_task(background_index_field(path))
    return {"status": "indexing", "active_field": str(path)}

@app.post("/api/update")
async def api_update():
    if not state.active_field:
        return {"error": "No active field"}
    try:
        result = await asyncio.to_thread(update_index, state.active_field)
        return {
            "status": "success",
            "indexed_files": result.indexed_files,
            "deleted_files": result.deleted_files
        }
    except Exception as e:
        return {"error": str(e)}

# -- Session Helper Functions --

def get_sessions_file(root: Path) -> Path:
    return root / ".palimind" / "sessions.json"

def load_sessions(root: Path) -> dict:
    file_path = get_sessions_file(root)
    if not file_path.exists():
        default_sess_id = str(uuid.uuid4())
        data = {
            "active_session_id": default_sess_id,
            "sessions": [
                {
                    "id": default_sess_id,
                    "name": "Default Session",
                    "created_at": time.time(),
                    "messages": []
                }
            ]
        }
        save_sessions(root, data)
        return data
    try:
        data = json.loads(file_path.read_text("utf-8"))
        if not data.get("sessions"):
            default_sess_id = str(uuid.uuid4())
            data = {
                "active_session_id": default_sess_id,
                "sessions": [
                    {
                        "id": default_sess_id,
                        "name": "Default Session",
                        "created_at": time.time(),
                        "messages": []
                    }
                ]
            }
            save_sessions(root, data)
        return data
    except Exception:
        default_sess_id = str(uuid.uuid4())
        data = {
            "active_session_id": default_sess_id,
            "sessions": [
                {
                    "id": default_sess_id,
                    "name": "Default Session",
                    "created_at": time.time(),
                    "messages": []
                }
            ]
        }
        save_sessions(root, data)
        return data

def save_sessions(root: Path, data: dict):
    file_path = get_sessions_file(root)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(data, indent=2), "utf-8")

def add_new_session(root: Path, name: str) -> dict:
    data = load_sessions(root)
    sess_id = str(uuid.uuid4())
    data["sessions"].append({
        "id": sess_id,
        "name": name,
        "created_at": time.time(),
        "messages": []
    })
    data["active_session_id"] = sess_id
    save_sessions(root, data)
    return data

def set_active_session_id(root: Path, session_id: str) -> dict:
    data = load_sessions(root)
    exists = any(s["id"] == session_id for s in data["sessions"])
    if exists:
        data["active_session_id"] = session_id
        save_sessions(root, data)
    return data

def delete_session(root: Path, session_id: str) -> dict:
    data = load_sessions(root)
    sessions = data["sessions"]
    data["sessions"] = [s for s in sessions if s["id"] != session_id]
    if not data["sessions"]:
        default_sess_id = str(uuid.uuid4())
        data["sessions"] = [
            {
                "id": default_sess_id,
                "name": "Default Session",
                "created_at": time.time(),
                "messages": []
            }
        ]
        data["active_session_id"] = default_sess_id
    elif data["active_session_id"] == session_id:
        data["active_session_id"] = data["sessions"][0]["id"]
    save_sessions(root, data)
    return data

def append_message_to_session(root: Path, session_id: str, role: str, content: str, sources: list[str] = None):
    data = load_sessions(root)
    for sess in data["sessions"]:
        if sess["id"] == session_id:
            if sess["name"] in ["Default Session", "New Session"]:
                if role == "user":
                    short_name = content[:30] + "..." if len(content) > 30 else content
                    sess["name"] = short_name
            
            msg = {
                "role": role,
                "content": content,
                "timestamp": time.time()
            }
            if sources:
                msg["sources"] = sources
            sess["messages"].append(msg)
            break
    save_sessions(root, data)

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

@app.get("/api/chat")
async def chat_stream(q: str, session_id: str | None = None, files: str | None = None):
    if not state.active_field:
        async def err_stream():
            yield f"data: {json.dumps({'type': 'error', 'text': 'No active field'})}\n\n"
        return StreamingResponse(err_stream(), media_type="text/event-stream")

    active_sess_id = session_id
    history_to_send = None
    if state.active_field:
        sessions_data = await asyncio.to_thread(load_sessions, state.active_field)
        if not active_sess_id:
            active_sess_id = sessions_data.get("active_session_id")
        
        if active_sess_id:
            for sess in sessions_data.get("sessions", []):
                if sess["id"] == active_sess_id:
                    history_to_send = []
                    for msg in sess.get("messages", [])[-10:]:
                        role = msg["role"]
                        if role == "system":
                            role = "assistant"
                        history_to_send.append({
                            "role": role,
                            "content": msg["content"]
                        })
                    break

    files_filter = None
    if files:
        files_filter = [f.strip() for f in files.split(",") if f.strip()]

    try:
        context, stream = await asyncio.to_thread(
            query_stream,
            state.active_field,
            q,
            history=history_to_send,
            files_filter=files_filter
        )
    except Exception as e:
        error_msg = str(e)
        async def err_stream():
            yield f"data: {json.dumps({'type': 'error', 'text': error_msg})}\n\n"
        return StreamingResponse(err_stream(), media_type="text/event-stream")

    async def event_generator() -> AsyncGenerator[str, None]:
        import threading
        sources = list(context.sources) if context.sources else []
        yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"

        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def producer():
            try:
                for token in stream:
                    loop.call_soon_threadsafe(queue.put_nowait, token)
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, e)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        threading.Thread(target=producer, daemon=True).start()

        full_response = []
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                if isinstance(item, Exception):
                    yield f"data: {json.dumps({'type': 'error', 'text': str(item)})}\n\n"
                    break
                full_response.append(item)
                yield f"data: {json.dumps({'type': 'token', 'text': item})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"

        bot_answer = "".join(full_response)
        if bot_answer and active_sess_id:
            await asyncio.to_thread(
                append_message_to_session,
                state.active_field,
                active_sess_id,
                "user",
                q
            )
            await asyncio.to_thread(
                append_message_to_session,
                state.active_field,
                active_sess_id,
                "system",
                bot_answer,
                sources
            )

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

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

def run_server(port: int = 8000):
    uvicorn.run(app, host="127.0.0.1", port=port)
