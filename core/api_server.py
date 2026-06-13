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
from core.email_api_router import router as email_router

app = FastAPI(title="Palimind V2 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(email_router)

UI_DIR = Path(__file__).parent.parent / "ui"
if UI_DIR.exists():
    app.mount("/ui/static", StaticFiles(directory=UI_DIR / "static"), name="static")

    @app.get("/ui", response_class=HTMLResponse)
    @app.get("/ui/", response_class=HTMLResponse)
    async def serve_ui():
        index_file = UI_DIR / "template" / "index.html"
        return index_file.read_text("utf-8")

    @app.get("/ui/hotkey", response_class=HTMLResponse)
    async def serve_hotkey():
        hotkey_file = UI_DIR / "template" / "hotkey.html"
        return hotkey_file.read_text("utf-8")

# -- Global State & Config --
GLOBAL_CONFIG_PATH = Path.home() / ".palimind_global.json"
GLOBAL_AGENTS_PATH = Path.home() / ".palimind_agents.json"

def get_default_agents():
    return [
        {
            "id": "research",
            "name": "Research",
            "description": "researches deep in the documents.",
            "system_prompt": (
                "You are an expert Research Agent. Your goal is to provide deep, analytical, and highly structured insights based "
                "on the provided context. Follow these reasoning steps:\n"
                "1. Break down the user's query into core concepts.\n"
                "2. Systematically search the context for evidence matching these concepts.\n"
                "3. Synthesize your findings into a comprehensive report, using clear headings, bullet points, and logical flow.\n"
                "Always favor precision and factual accuracy over assumption. Cite your sources clearly using inline brackets [filename] "
                "for every claim."
            ),
            "is_default": True
        },
        {
            "id": "compare",
            "name": "Compare",
            "description": "multi document comparison",
            "system_prompt": (
                "You are an expert Comparison Agent. Your goal is to analyze multiple documents and provide a structured, objective "
                "comparison. Follow these reasoning steps:\n"
                "1. Identify the key entities, concepts, or documents being compared.\n"
                "2. Establish clear criteria for comparison (e.g., pros/cons, similarities/differences, performance metrics).\n"
                "3. Present your analysis using tables or structured bullet points for maximum clarity.\n"
                "Always cite your sources clearly using inline brackets [filename]."
            ),
            "is_default": True
        },
        {
            "id": "advise",
            "name": "Advise",
            "description": "advises",
            "system_prompt": (
                "You are an expert Advisory Agent. Your goal is to provide highly practical, actionable, and logical advice. "
                "Follow these reasoning steps:\n"
                "1. Analyze the user's situation and goals based on the query.\n"
                "2. Evaluate the provided context for constraints, best practices, and relevant solutions.\n"
                "3. Present clear recommendations, ordered by priority, explaining the 'why' behind each piece of advice.\n"
                "Always cite your sources clearly using inline brackets [filename]."
            ),
            "is_default": True
        }
    ]

def load_agents() -> list[dict]:
    if GLOBAL_AGENTS_PATH.exists():
        try:
            data = json.loads(GLOBAL_AGENTS_PATH.read_text("utf-8"))
            return data.get("agents", get_default_agents())
        except Exception:
            return get_default_agents()
    else:
        agents = get_default_agents()
        save_agents(agents)
        return agents

def save_agents(agents: list[dict]):
    try:
        GLOBAL_AGENTS_PATH.write_text(json.dumps({"agents": agents}, indent=2), "utf-8")
    except Exception as e:
        print(f"Failed to save agents: {e}")

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

async def background_update_memory(root: Path, session_id: str, new_user_msg: str, new_bot_msg: str):
    await asyncio.sleep(2) # Allow Ollama to breathe and prioritize new user queries
    from core.config import load_config
    from core.generative.summariser import summarise_conversation
    from core.storage.chat_store import ChatVectorStore
    from core.retrieval.embedder import generate_embeddings_batch
    import uuid

    config = load_config(root)
    ollama_url = config.get("ollama_base_url")
    chat_model = config.get("chat_model")
    embed_model = config.get("embed_model")
    
    # 1. Update mid-term summary
    sessions_data = load_sessions(root)
    target_sess = next((s for s in sessions_data.get("sessions", []) if s["id"] == session_id), None)
    if not target_sess:
        return
        
    recent_messages = target_sess.get("messages", [])[-6:]
    previous_summary = target_sess.get("summary", "")
    
    try:
        new_summary = await asyncio.to_thread(
            summarise_conversation,
            recent_messages,
            previous_summary,
            ollama_url,
            chat_model
        )
        if new_summary:
            target_sess["summary"] = new_summary
            save_sessions(root, sessions_data)
    except Exception as e:
        print(f"Failed to update summary: {e}")
        
    # 2. Update long-term episodic memory
    turn_content = f"User: {new_user_msg}\nAssistant: {new_bot_msg}"
    try:
        embs = await asyncio.to_thread(generate_embeddings_batch, [turn_content], ollama_url, embed_model)
        if embs and embs[0]:
            chunk_id = int(uuid.uuid4().int % (2**63))
            with ChatVectorStore(root) as vstore:
                vstore.insert([{
                    "vector": embs[0],
                    "chunk_id": chunk_id,
                    "session_id": session_id,
                    "content": turn_content
                }])
    except Exception as e:
        print(f"Failed to update episodic memory: {e}")

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

@app.get("/api/agents")
async def get_agents():
    return {"agents": load_agents()}

@app.post("/api/agents/new")
async def create_agent(req: Request):
    data = await req.json()
    agents = load_agents()
    new_agent = {
        "id": str(uuid.uuid4()),
        "name": data.get("name", "New Agent"),
        "description": data.get("description", ""),
        "system_prompt": data.get("system_prompt", "You are a helpful assistant."),
        "is_default": False
    }
    agents.append(new_agent)
    save_agents(agents)
    return {"status": "success", "agent": new_agent}

@app.post("/api/agents/edit")
async def edit_agent(req: Request):
    data = await req.json()
    agent_id = data.get("id")
    agents = load_agents()
    for i, a in enumerate(agents):
        if a["id"] == agent_id and not a.get("is_default"):
            agents[i]["name"] = data.get("name", a["name"])
            agents[i]["description"] = data.get("description", a["description"])
            agents[i]["system_prompt"] = data.get("system_prompt", a["system_prompt"])
            save_agents(agents)
            return {"status": "success", "agent": agents[i]}
    return {"error": "Agent not found or is default"}

@app.post("/api/agents/remove")
async def remove_agent(req: Request):
    data = await req.json()
    agent_id = data.get("id")
    agents = load_agents()
    original_len = len(agents)
    agents = [a for a in agents if not (a["id"] == agent_id and not a.get("is_default"))]
    if len(agents) < original_len:
        save_agents(agents)
        return {"status": "success"}
    return {"error": "Agent not found or is default"}

@app.get("/api/chat")
async def chat_stream(q: str, session_id: str | None = None, files: str | None = None, chat_mode: str = "rag", agent_id: str | None = None):
    if not state.active_field:
        async def err_stream():
            yield f"data: {json.dumps({'type': 'error', 'text': 'No active field'})}\n\n"
        return StreamingResponse(err_stream(), media_type="text/event-stream")

    active_sess_id = session_id
    history_to_send = None
    mid_term_summary = None
    if state.active_field:
        sessions_data = await asyncio.to_thread(load_sessions, state.active_field)
        if not active_sess_id:
            active_sess_id = sessions_data.get("active_session_id")
        
        if active_sess_id:
            for sess in sessions_data.get("sessions", []):
                if sess["id"] == active_sess_id:
                    mid_term_summary = sess.get("summary")
                    history_to_send = []
                    for msg in sess.get("messages", [])[-5:]:
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
        from core.agent import reformulate_query, needs_retrieval
        from core.config import load_config
        from core.querying import query_stream_with_diagnostics
        config = load_config(state.active_field)
        ollama_url = config.get("ollama_base_url", "https://puny-aliens-film.loca.lt")
        chat_model = config.get("chat_model", "llama3")

        agent_system_prompt = None
        if agent_id:
            agents = await asyncio.to_thread(load_agents)
            for a in agents:
                if a["id"] == agent_id:
                    agent_system_prompt = a["system_prompt"]
                    break

        if chat_mode == "llm":
            needs_retrieval_fast = False
        else:
            needs_retrieval_fast = await asyncio.to_thread(
                needs_retrieval, q, history_to_send or [], ollama_url, chat_model
            )

        diagnostics_report = None

        if needs_retrieval_fast:
            standalone_query = await asyncio.to_thread(
                reformulate_query, q, history_to_send or [], ollama_url, chat_model
            )
            context, stream, diagnostics_report = await asyncio.to_thread(
                query_stream_with_diagnostics,
                state.active_field,
                standalone_query,
                system_prompt=agent_system_prompt,
                history=history_to_send,
                files_filter=files_filter,
                mid_term_summary=mid_term_summary,
                session_id=active_sess_id
            )
        else:
            from core.generative.responder import generate_response_stream
            from core.models import RetrievedContext
            
            prompt = agent_system_prompt or "You are a helpful assistant."
            if mid_term_summary:
                prompt = f"{prompt}\n\nConversation Summary so far:\n{mid_term_summary}"

            context = RetrievedContext(text_contexts=(), image_paths=(), sources=())
            
            stream = generate_response_stream(
                query=q,
                context="",
                image_paths=[],
                ollama_url=ollama_url,
                chat_model=chat_model,
                system_prompt=prompt,
                history=history_to_send,
                is_chat_only=True
            )

    except Exception as e:
        error_msg = str(e)
        async def err_stream():
            yield f"data: {json.dumps({'type': 'error', 'text': error_msg})}\n\n"
        return StreamingResponse(err_stream(), media_type="text/event-stream")

    async def event_generator() -> AsyncGenerator[str, None]:
        import threading
        sources = list(context.sources) if context.sources else []
        
        # Emit sources with task_type metadata
        task_type_str = ""
        if diagnostics_report:
            task_type_str = diagnostics_report.task_type
        yield f"data: {json.dumps({'type': 'sources', 'sources': sources, 'task_type': task_type_str})}\n\n"

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
            asyncio.create_task(background_update_memory(state.active_field, active_sess_id, q, bot_answer))

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

        # Emit diagnostics after done (non-blocking for client)
        if diagnostics_report:
            try:
                diag_dict = diagnostics_report.to_dict()
                yield f"data: {json.dumps({'type': 'diagnostics', 'data': diag_dict})}\n\n"
            except Exception:
                pass

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

# -- Model Switcher & Config Endpoints --

def _fetch_ollama_models_blocking(ollama_url: str) -> list[dict]:
    """Fetch available models from Ollama API."""
    import urllib.request
    import urllib.error

    base = ollama_url.rstrip("/")
    url = f"{base}/api/tags"
    try:
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", "Palimind/2.0")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = []
            for m in data.get("models", []):
                name = m.get("name", "")
                size_bytes = m.get("size", 0)
                size_gb = round(size_bytes / (1024**3), 1) if size_bytes else 0
                param_size = m.get("details", {}).get("parameter_size", "")
                family = m.get("details", {}).get("family", "")
                models.append({
                    "model_id": name,
                    "display_name": name,
                    "family": family,
                    "parameter_size": param_size,
                    "size_gb": size_gb,
                    "provider": "ollama",
                })
            return models
    except Exception as e:
        print(f"Failed to fetch Ollama models: {e}")
        return []


@app.get("/api/models")
async def get_models():
    """Fetch available models from configured Ollama instance."""
    from core.config import load_config
    config = {}
    if state.active_field:
        config = load_config(state.active_field)
    ollama_url = config.get("ollama_base_url", "https://mighty-eggs-move.loca.lt")
    current_model = config.get("chat_model", "gemma4:e2b")
    try:
        models = await asyncio.to_thread(_fetch_ollama_models_blocking, ollama_url)
        return {
            "models": models,
            "current_model": current_model,
            "ollama_url": ollama_url,
        }
    except Exception as e:
        return {"error": str(e), "models": [], "current_model": current_model}


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
        "ollama_base_url": config.get("ollama_base_url", "https://mighty-eggs-move.loca.lt"),
    }


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
    uvicorn.run("core.api_server:app", host="127.0.0.1", port=port)

if __name__ == "__main__":
    run_server()
