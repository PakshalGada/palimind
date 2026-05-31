import base64
import httpx
from pathlib import Path

def caption_image(file_path: Path, ollama_url: str, vision_model: str) -> str:
    """
    Use Ollama HTTP API to generate a caption for the given image.
    """
    try:
        with open(file_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")
            
        payload = {
            "model": vision_model,
            "prompt": "Provide a detailed semantic description of this image. Describe any text, objects, layout, and context visible.",
            "images": [image_data],
            "stream": False
        }
        
        url = f"{ollama_url.rstrip('/')}/api/generate"
        response = httpx.post(url, json=payload, timeout=60.0)
        response.raise_for_status()
        
        return response.json().get("response", "").strip()
    except Exception as e:
        print(f"Error captioning image {file_path}: {e}")
        return ""
