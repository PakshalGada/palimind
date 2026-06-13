"""
Vision Service for Palivision.

Tries to use a locally-installed Ollama vision model (llava, moondream2, etc.)
to generate a description of a screenshot.

This is optional — if the user hasn't pulled a vision model, this returns None
and the system falls back to OCR-only mode.

To install a vision model, the user runs one of:
    ollama pull llava         (4B, good quality, needs ~5GB RAM)
    ollama pull moondream2    (1.8B, faster, less RAM needed)
"""

import logging

import httpx

logger = logging.getLogger(__name__)

# Ollama server address — same as what PaliMind already uses
OLLAMA_BASE_URL = "https://plain-masks-jump.loca.lt"

# We try these models in order. First one that responds wins.
VISION_MODELS_TO_TRY = ["llava", "moondream2", "minicpm-v", "llava-phi3"]


async def describe_screenshot(image_b64: str) -> str | None:
    """
    Sends a base64-encoded screenshot to a local Ollama vision model.
    Returns a text description of what's on screen, or None if no vision model
    is available.

    Args:
        image_b64: Base64-encoded PNG (no data URL prefix)

    Returns:
        A string describing the screen content, or None if unavailable.
    """
    prompt = (
        "You are analyzing a screenshot. Describe exactly what you see: "
        "what application is open, what text is visible, what the user is doing, "
        "any errors or warnings shown, and any important data on screen. "
        "Be specific and factual."
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        for model_name in VISION_MODELS_TO_TRY:
            try:
                logger.info(f"[Palivision Vision] Trying Ollama vision model: {model_name}")
                response = await client.post(
                    f"{OLLAMA_BASE_URL}/api/generate",
                    json={
                        "model": model_name,
                        "prompt": prompt,
                        "images": [image_b64],  # Ollama expects raw base64, no prefix
                        "stream": False,
                    }
                )
                if response.status_code == 200:
                    description = response.json().get("response", "").strip()
                    if description:
                        logger.info(f"[Palivision Vision] Got description from {model_name} ({len(description)} chars)")
                        return description
            except httpx.TimeoutException:
                logger.warning(f"[Palivision Vision] Model {model_name} timed out, trying next.")
            except Exception as e:
                logger.debug(f"[Palivision Vision] Model {model_name} failed: {e}")

    logger.info("[Palivision Vision] No vision model available. Using OCR-only mode.")
    return None
