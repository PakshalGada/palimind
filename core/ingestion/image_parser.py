import base64
from pathlib import Path

import httpx

from core.exceptions import CaptionError


def caption_image(file_path: Path, ollama_url: str, vision_model: str) -> str:
    """Use Ollama HTTP API to generate a caption for the given image."""
    try:
        image_data = base64.b64encode(file_path.read_bytes()).decode("utf-8")
        payload = {
            "model": vision_model,
            "prompt": (
                "Provide a detailed semantic description of this image. "
                "Describe any text, objects, layout, and context visible."
            ),
            "images": [image_data],
            "stream": False,
        }
        url = f"{ollama_url.rstrip('/')}/api/generate"
        response = httpx.post(url, json=payload, timeout=60.0)
        response.raise_for_status()
        return response.json().get("response", "").strip()
    except httpx.HTTPError as e:
        raise CaptionError(f"Error captioning image {file_path}: {e}") from e
    except OSError as e:
        raise CaptionError(f"Error reading image {file_path}: {e}") from e
