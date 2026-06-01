import httpx

from core.exceptions import EmbeddingError


def generate_embedding(text: str, ollama_url: str, embed_model: str) -> list[float]:
    """Generate an embedding for a given text using Ollama."""
    url = f"{ollama_url.rstrip('/')}/api/embeddings"
    payload = {"model": embed_model, "prompt": text}
    try:
        response = httpx.post(url, json=payload, timeout=60.0)
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise EmbeddingError(f"Failed to generate embedding: {e}") from e

    embedding = response.json().get("embedding", [])
    if not embedding:
        raise EmbeddingError("Ollama returned an empty embedding")
    return embedding


def generate_embeddings_batch(
    texts: list[str], ollama_url: str, embed_model: str
) -> list[list[float]]:
    """Generate embeddings for multiple texts sequentially."""
    return [generate_embedding(text, ollama_url, embed_model) for text in texts]
