"""
Vision Service for Palivision.

Tries to use a locally-installed Ollama vision model (llava, moondream, etc.)
to generate a description of a screenshot.

This is optional — if the user hasn't pulled a vision model, returns None
and the system falls back to OCR-only mode.

Recommended pulls (pick ONE based on available RAM):
    ollama pull moondream        # Lightweight,   ~1.7 GB  ← recommended default
    ollama pull llava-phi3       # Balanced,      ~2.9 GB
    ollama pull llava:7b         # Best quality,  ~4.7 GB
"""

import json
import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# Fallback — overridden at call time by _resolve_ollama_url() reading global config
OLLAMA_BASE_URL = "http://localhost:11434"

# Ordered by preference: fastest/lightest first.
# moondream (~1.7 GB) is the recommended default.
VISION_MODELS_TO_TRY = ["moondream2", "llava-phi3", "llava", "minicpm-v"]

# Cold-start loads (model → VRAM) can take 40-90 s on a CPU-only machine.
VISION_TIMEOUT_SECONDS = 120.0


def _resolve_ollama_url(override: str | None) -> str:
    """Return the Ollama URL from an explicit override, global config, or built-in fallback."""
    if override:
        return override.rstrip("/")
    cfg_path = Path.home() / ".palimind" / "config.json"
    if cfg_path.exists():
        try:
            return json.loads(cfg_path.read_text("utf-8")).get(
                "ollama_base_url", OLLAMA_BASE_URL
            ).rstrip("/")
        except Exception:
            pass
    return OLLAMA_BASE_URL


async def _get_installed_vision_models(client: httpx.AsyncClient, ollama_url: str) -> set[str]:
    """
    Pre-flight /api/tags to find installed models so we don't waste
    timeout budget probing models the user never pulled.
    Returns bare model names (no \":latest\" suffix).
    """
    try:
        resp = await client.get(f"{ollama_url}/api/tags", timeout=8.0)
        if resp.status_code == 200:
            models_data = resp.json().get("models", [])
            return {m["name"].split(":")[0] for m in models_data if "name" in m}
    except Exception as e:
        logger.debug(f"[Palivision Vision] Could not fetch installed models: {e}")
    return set()


async def describe_screenshot(image_b64: str, ollama_url: str | None = None) -> str | None:
    """
    Sends a base64-encoded screenshot to a local Ollama vision model.
    Returns a text description of what's on screen, or None if no vision model
    is available.

    Args:
        image_b64: Base64-encoded PNG (no data URL prefix)
        ollama_url: Ollama server URL; if None, reads from global config.

    Returns:
        A string describing the screen content, or None if unavailable.
    """
    if not image_b64:
        return None

    resolved_url = _resolve_ollama_url(ollama_url)

    prompt = (
        "You are analyzing a screenshot. Describe exactly what you see: "
        "what application is open, what text is visible, what the user is doing, "
        "any errors or warnings shown, and any important data on screen. "
        "Be specific and factual. Keep your answer under 200 words."
    )

    async with httpx.AsyncClient(timeout=VISION_TIMEOUT_SECONDS) as client:
        # Pre-check which vision models are actually installed
        installed = await _get_installed_vision_models(client, resolved_url)
        logger.info(f"[Palivision Vision] Installed models: {installed}")

        candidates = [m for m in VISION_MODELS_TO_TRY if m in installed]
        if not candidates:
            logger.info(
                "[Palivision Vision] No vision model installed. "
                "Run: ollama pull moondream   (~1.7 GB, fastest)"
            )
            return None

        for model_name in candidates:
            try:
                logger.info(f"[Palivision Vision] Trying model: {model_name}")
                response = await client.post(
                    f"{resolved_url}/api/chat",
                    json={
                        "model": model_name,
                        "messages": [
                            {
                                "role": "user",
                                "content": prompt,
                                "images": [image_b64],
                            }
                        ],
                        "stream": False,
                        "options": {"num_predict": 256},
                    },
                )
                if response.status_code == 200:
                    description = (
                        response.json()
                        .get("message", {})
                        .get("content", "")
                        .strip()
                    )
                    if description:
                        logger.info(
                            f"[Palivision Vision] Got description from {model_name} "
                            f"({len(description)} chars)"
                        )
                        return description
                    else:
                        logger.warning(f"[Palivision Vision] {model_name} returned empty description.")
                else:
                    logger.warning(f"[Palivision Vision] {model_name} returned HTTP {response.status_code}")

            except httpx.TimeoutException:
                logger.warning(
                    f"[Palivision Vision] {model_name} timed out after "
                    f"{VISION_TIMEOUT_SECONDS}s. Trying next."
                )
            except Exception as e:
                logger.debug(f"[Palivision Vision] {model_name} failed: {e}")

    logger.info("[Palivision Vision] All vision models failed. Using OCR-only mode.")
    return None
