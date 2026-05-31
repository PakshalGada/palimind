import httpx

def generate_embedding(text: str, ollama_url: str, embed_model: str) -> list[float]:
    """
    Generate an embedding for a given text using Ollama.
    """
    try:
        url = f"{ollama_url.rstrip('/')}/api/embeddings"
        payload = {
            "model": embed_model,
            "prompt": text
        }
        response = httpx.post(url, json=payload, timeout=60.0)
        response.raise_for_status()
        return response.json().get("embedding", [])
    except Exception as e:
        print(f"Error generating embedding: {e}")
        return []

def generate_embeddings_batch(texts: list[str], ollama_url: str, embed_model: str) -> list[list[float]]:
    """
    Generate embeddings for multiple texts sequentially (or via batched API if supported).
    """
    # Ollama /api/embed supports batching in newer versions, 
    # but to be safe and compatible with /api/embeddings, we do sequential or concurrent.
    # Here we do sequential for simplicity, but in production we might use asyncio.gather.
    embeddings = []
    for text in texts:
        emb = generate_embedding(text, ollama_url, embed_model)
        embeddings.append(emb)
    return embeddings
