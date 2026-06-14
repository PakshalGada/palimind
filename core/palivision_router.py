"""
Palivision FastAPI Router.

Provides the POST /api/palivision/analyze endpoint.

The frontend sends:
  - image_b64: base64-encoded PNG of the current screen
  - user_prompt: the question the user typed
  - chat_model: (optional) which Ollama model to use for the final response

This endpoint:
  1. Runs EasyOCR on the image to extract visible text
  2. Optionally asks a local Ollama vision model to describe the screen
  3. Builds a context-rich system prompt
  4. Streams a response from the Ollama chat model using Server-Sent Events

The frontend reads the SSE stream and appends each token to the chat UI.
"""

import json
import logging
from pathlib import Path

import httpx
from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.services.ocr_service import extract_text_from_b64
from core.services.vision_service import describe_screenshot

logger = logging.getLogger(__name__)

# This router is registered in core/api_server.py
# All endpoints here are accessible at /api/palivision/...
router = APIRouter(prefix="/api/palivision", tags=["palivision"])

# Ollama server — same address PaliMind already uses
OLLAMA_BASE_URL = "https://cuddly-lines-rhyme.loca.lt"

# Default chat model — matches PaliMind's existing default
DEFAULT_CHAT_MODEL = "gemma4:e2b"


class PalivisionRequest(BaseModel):
    """Request body for the /analyze endpoint."""
    # Base64-encoded PNG screenshot. No "data:image/png;base64," prefix — just the raw base64.
    image_b64: str
    # The question the user typed in the Palivision chat box
    user_prompt: str
    # Which Ollama model to use for the final chat response
    # Which Ollama model to use for the final chat response
    chat_model: str = DEFAULT_CHAT_MODEL
    # Web search toggle
    web_search: bool = False
    # Prior conversation history
    messages: list[dict] = []


@router.post("/analyze")
async def analyze_screen(req: PalivisionRequest):
    """
    Main Palivision endpoint.

    Receives a screenshot + question, runs OCR + vision analysis,
    then streams an Ollama response back via Server-Sent Events.

    SSE format (what the frontend reads):
      data: {"token": "Hello"}
      data: {"token": " world"}
      data: [DONE]
    """

    # --- Step 1: Run EasyOCR to extract all visible text from the screenshot ---
    logger.info("[Palivision] Starting OCR analysis...")
    ocr_text = extract_text_from_b64(req.image_b64)

    # --- Step 2: Resolve Ollama URL once (used for both vision + chat) ---
    _glance_root = Path.home() / ".palimind"
    _global_cfg_path = _glance_root / "config.json"
    _ollama_url = OLLAMA_BASE_URL
    if _global_cfg_path.exists():
        try:
            _ollama_url = json.loads(_global_cfg_path.read_text("utf-8")).get("ollama_base_url", OLLAMA_BASE_URL)
        except Exception:
            pass

    # --- Step 3: Try to get a vision description (optional) ---
    logger.info("[Palivision] Attempting vision model analysis...")
    vision_description = await describe_screenshot(req.image_b64, ollama_url=_ollama_url)

    # --- Step 3: Build the system prompt that gives the AI context about the screen ---
    context_sections = []

    if ocr_text:
        context_sections.append(
            f"TEXT VISIBLE ON SCREEN (extracted via OCR):\n{ocr_text}"
        )
    else:
        context_sections.append("TEXT VISIBLE ON SCREEN: (no text detected)")

    if vision_description:
        context_sections.append(
            f"VISUAL DESCRIPTION OF SCREEN:\n{vision_description}"
        )

    screen_context = "\n\n".join(context_sections)

    system_prompt = (
        "You are PaliMind, a local AI assistant with full visibility of the user's current screen. "
        "The user has shared a screenshot with you. "
        "Use the screen context below to answer their question precisely and helpfully.\n\n"
        f"{screen_context}\n\n"
        "Answer based on what is actually visible on the screen. "
        "If the screen context does not contain enough information to answer, say so clearly."
    )

    if req.web_search:
        import asyncio
        from core.web_search import perform_web_search
        try:
            web_results = await asyncio.to_thread(perform_web_search, req.user_prompt)
            if web_results:
                system_prompt += f"\n\nWEB SEARCH RESULTS FOR CONTEXT:\n{web_results}"
        except Exception as e:
            logger.warning(f"[Palivision] Web search failed: {e}")

    logger.info(f"[Palivision] System prompt built ({len(system_prompt)} chars). Streaming response...")

    # --- Step 4: Stream response from Ollama chat model ---
    async def generate_sse():
        """
        Generator function that calls Ollama's streaming API and
        converts each token into an SSE-formatted data line.
        """
        try:
            yield f"data: {json.dumps({'type': 'screen_context', 'summary': ocr_text[:200] if ocr_text else ''})}\n\n"

            # Ollama URL already resolved above — reuse via closure

            ollama_messages = [{"role": "system", "content": system_prompt}]
            
            for prior in req.messages:
                role = prior.get("role")
                content = prior.get("content", "")
                if role in ("user", "assistant") and content:
                    ollama_messages.append({"role": role, "content": content})
                    
            ollama_messages.append({"role": "user", "content": req.user_prompt})

            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    f"{_ollama_url}/api/chat",
                    json={
                        "model": req.chat_model,
                        "messages": ollama_messages,
                        "stream": True
                    }
                ) as response:
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            token = data.get("message", {}).get("content", "")
                            if token:
                                # Send each token as a Server-Sent Event
                                yield f"data: {json.dumps({'token': token})}\n\n"
                        except json.JSONDecodeError:
                            continue

            # Signal to the frontend that streaming is complete
            yield "data: [DONE]\n\n"

        except httpx.ConnectError:
            error_msg = "Cannot connect to Ollama. Make sure Ollama is running: run 'ollama serve' in a terminal."
            logger.error(f"[Palivision] {error_msg}")
            yield f"data: {json.dumps({'token': error_msg})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            error_msg = f"Error generating response: {str(e)}"
            logger.error(f"[Palivision] {error_msg}")
            yield f"data: {json.dumps({'token': error_msg})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Prevents Nginx from buffering the stream
        }
    )


@router.get("/warmup")
async def warmup_ocr():
    """
    Optional endpoint to pre-load the EasyOCR model at startup.
    Call GET /api/palivision/warmup to avoid the ~5s delay on first use.
    PaliMind can call this automatically if desired.
    Returns status 'ok' even if EasyOCR is not installed (graceful degradation).
    """
    try:
        from core.services.ocr_service import _get_reader
        _get_reader()  # This triggers the cached model load
        return {"status": "ok", "message": "OCR model loaded and ready."}
    except ImportError:
        return {"status": "degraded", "message": "EasyOCR not installed. Install with: pip install easyocr"}
    except Exception as e:
        logger.warning(f"[Palivision] OCR warmup failed: {e}")
        return {"status": "degraded", "message": f"OCR warmup failed: {e}"}



# ── Session Persistence ───────────────────────────────────────────────────
from pathlib import Path

GLANCE_SESSIONS_PATH = Path.home() / ".palimind" / "glance_sessions.json"

def load_glance_sessions() -> dict:
    if GLANCE_SESSIONS_PATH.exists():
        try:
            return json.loads(GLANCE_SESSIONS_PATH.read_text("utf-8"))
        except Exception:
            pass
    return {"sessions": []}

def save_glance_sessions(data: dict):
    GLANCE_SESSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    GLANCE_SESSIONS_PATH.write_text(json.dumps(data, indent=2), "utf-8")


class GlanceSessionSaveRequest(BaseModel):
    session_id: str
    title: str
    messages: list[dict]          # [{"role": "user"|"assistant", "content": "...", "ts": 123}]
    screen_summary: str = ""      # OCR/vision summary — for memory retrieval
    screenshot_b64: str = ""      # Raw base64 PNG of the captured screen
    ocr_text: str = ""            # Full OCR text extracted from screen
    chat_model: str = ""          # NEW: Selected Ollama chat model


@router.post("/session/save")
async def save_glance_session(req: GlanceSessionSaveRequest):
    """
    Save or update a PaliGlance conversation to ~/.palimind/glance_sessions.json.
    Called from glance.js after each assistant response.
    """
    data = load_glance_sessions()
    existing = next((s for s in data["sessions"] if s["id"] == req.session_id), None)
    import time
    if existing:
        existing["messages"] = req.messages
        existing["title"] = req.title
        existing["updated_at"] = int(time.time())
        # Update screenshot/ocr only if provided (don't overwrite with empty on follow-up saves)
        if req.screenshot_b64:
            existing["screenshot_b64"] = req.screenshot_b64
        if req.ocr_text:
            existing["ocr_text"] = req.ocr_text
        if req.chat_model:
            existing["chat_model"] = req.chat_model
    else:
        data["sessions"].insert(0, {
            "id": req.session_id,
            "title": req.title,
            "messages": req.messages,
            "screen_summary": req.screen_summary,
            "screenshot_b64": req.screenshot_b64,
            "ocr_text": req.ocr_text,
            "chat_model": req.chat_model,
            "created_at": int(time.time()),
            "updated_at": int(time.time()),
        })
    save_glance_sessions(data)
    return {"status": "saved", "session_id": req.session_id}


@router.get("/sessions")
async def get_glance_sessions():
    """Return all saved PaliGlance sessions for the PaliSpace sidebar."""
    data = load_glance_sessions()
    return data


@router.delete("/session/{session_id}")
async def delete_glance_session(session_id: str):
    data = load_glance_sessions()
    data["sessions"] = [s for s in data["sessions"] if s["id"] != session_id]
    save_glance_sessions(data)
    return {"status": "deleted"}


# ── Memory Integration ────────────────────────────────────────────────────
class GlanceMemoryRequest(BaseModel):
    session_id: str
    user_message: str
    assistant_message: str
    screen_summary: str = ""


@router.post("/memory/update")
async def update_glance_memory(req: GlanceMemoryRequest, background_tasks: BackgroundTasks):
    """
    Index a PaliGlance conversation turn into the global episodic memory.
    Uses ~/.palimind as the root so memories are accessible across all fields.
    """
    import asyncio

    # ChatVectorStore expects a project ROOT — it appends .palimind/ internally via palimind_dir().
    # So we must pass Path.home() (not Path.home()/'.palimind') to avoid doubling the subdir.
    glance_root = Path.home()
    glance_dot_dir = Path.home() / ".palimind"
    glance_dot_dir.mkdir(parents=True, exist_ok=True)

    # Import the same memory pipeline used by the main chat
    from core.storage.chat_store import ChatVectorStore
    from core.retrieval.embedder import generate_embeddings_batch
    import uuid

    # Load global config for model settings
    global_config_path = glance_dot_dir / "config.json"
    config = {}
    if global_config_path.exists():
        try:
            config = json.loads(global_config_path.read_text("utf-8"))
        except Exception:
            pass

    ollama_url = config.get("ollama_base_url", OLLAMA_BASE_URL)
    embed_model = config.get("embed_model", "nomic-embed-text")

    turn_content = (
        f"[PaliGlance Screen Analysis]\n"
        f"Screen context: {req.screen_summary}\n"
        f"User: {req.user_message}\n"
        f"Assistant: {req.assistant_message}"
    )

    async def do_embed():
        try:
            embs = await asyncio.to_thread(
                generate_embeddings_batch, [turn_content], ollama_url, embed_model
            )
            if embs and embs[0]:
                chunk_id = int(uuid.uuid4().int % (2**63))
                with ChatVectorStore(glance_root) as vstore:
                    vstore.insert([{
                        "vector": embs[0],
                        "chunk_id": chunk_id,
                        "session_id": req.session_id,
                        "content": turn_content
                    }])
                logger.info(f"[Palivision] Memory indexed for session {req.session_id}")
        except Exception as e:
            logger.warning(f"[Palivision] Memory update failed: {e}")

    background_tasks.add_task(do_embed)
    return {"status": "queued"}

