import json
import base64
import httpx
from pathlib import Path

def encode_image(image_path: str) -> str:
    try:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        print(f"Failed to encode image {image_path}: {e}")
        return None

def generate_response_stream(
    query: str, 
    context: str, 
    image_paths: list[str], 
    ollama_url: str, 
    chat_model: str,
    system_prompt: str
):
    """
    Yields chunks of the response from Ollama.
    """
    messages = []
    
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
        
    user_content = f"Context information is below:\n---------------------\n{context}\n---------------------\n\nGiven the context information and not prior knowledge, answer the query.\nQuery: {query}\nAnswer:"
    
    user_message = {"role": "user", "content": user_content}
    
    if image_paths:
        images = []
        for path in image_paths:
            if Path(path).exists():
                b64 = encode_image(path)
                if b64:
                    images.append(b64)
        if images:
            user_message["images"] = images
            
    messages.append(user_message)
    
    url = f"{ollama_url.rstrip('/')}/api/chat"
    payload = {
        "model": chat_model,
        "messages": messages,
        "stream": True
    }
    
    try:
        with httpx.Client(timeout=60.0) as client:
            with client.stream("POST", url, json=payload) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line:
                        data = json.loads(line)
                        if "message" in data and "content" in data["message"]:
                            yield data["message"]["content"]
    except Exception as e:
        yield f"\n[Error generating response: {e}]"
