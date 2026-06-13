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

import httpx
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.services.ocr_service import extract_text_from_b64
from core.services.vision_service import describe_screenshot

logger = logging.getLogger(__name__)

# This router is registered in core/api_server.py
# All endpoints here are accessible at /api/palivision/...
router = APIRouter(prefix="/api/palivision", tags=["palivision"])

# Ollama server — same address PaliMind already uses
OLLAMA_BASE_URL = "https://plain-masks-jump.loca.lt"

# Default chat model — matches PaliMind's existing default
DEFAULT_CHAT_MODEL = "gemma4:e2b"


class PalivisionRequest(BaseModel):
    """Request body for the /analyze endpoint."""
    # Base64-encoded PNG screenshot. No "data:image/png;base64," prefix — just the raw base64.
    image_b64: str
    # The question the user typed in the Palivision chat box
    user_prompt: str
    # Which Ollama model to use for the final chat response
    chat_model: str = DEFAULT_CHAT_MODEL


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

    # --- Step 2: Try to get a vision description (optional) ---
    logger.info("[Palivision] Attempting vision model analysis...")
    vision_description = await describe_screenshot(req.image_b64)

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

    logger.info(f"[Palivision] System prompt built ({len(system_prompt)} chars). Streaming response...")

    # --- Step 4: Stream response from Ollama chat model ---
    async def generate_sse():
        """
        Generator function that calls Ollama's streaming API and
        converts each token into an SSE-formatted data line.
        """
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    f"{OLLAMA_BASE_URL}/api/chat",
                    json={
                        "model": req.chat_model,
                        "messages": [
                            {
                                "role": "system",
                                "content": system_prompt
                            },
                            {
                                "role": "user",
                                "content": req.user_prompt
                            }
                        ],
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
    """
    from core.services.ocr_service import _get_reader
    _get_reader()  # This triggers the cached model load
    return {"status": "ok", "message": "OCR model loaded and ready."}
