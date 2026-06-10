from __future__ import annotations

import functools
import httpx

from core.exceptions import EmbeddingError


@functools.lru_cache(maxsize=128)
def generate_embedding(text: str, ollama_url: str, embed_model: str) -> list[float]:
    """Generate an embedding for a single text using Ollama."""
    url = f"{ollama_url.rstrip('/')}/api/embed"
    payload = {"model": embed_model, "input": text}
    try:
        response = httpx.post(url, json=payload, timeout=120.0)
        response.raise_for_status()
    except httpx.TimeoutException as e:
        raise EmbeddingError(f"Embedding request timed out: {e}") from e
    except httpx.HTTPError as e:
        raise EmbeddingError(f"Failed to generate embedding: {e}") from e

    data = response.json()
    embeddings = data.get("embeddings", [])
    if not embeddings or not embeddings[0]:
        raise EmbeddingError("Ollama returned an empty embedding")
    return embeddings[0]


def generate_embeddings_batch(
    texts: list[str], ollama_url: str, embed_model: str
) -> list[list[float]]:
    """Generate embeddings for multiple texts in a single HTTP call."""
    if not texts:
        return []

    url = f"{ollama_url.rstrip('/')}/api/embed"
    payload = {"model": embed_model, "input": texts}
    try:
        response = httpx.post(url, json=payload, timeout=300.0)
        response.raise_for_status()
    except httpx.TimeoutException as e:
        raise EmbeddingError(f"Batch embedding request timed out: {e}") from e
    except httpx.HTTPError as e:
        raise EmbeddingError(f"Failed to generate batch embeddings: {e}") from e

    data = response.json()
    embeddings = data.get("embeddings", [])
    if len(embeddings) != len(texts):
        raise EmbeddingError(
            f"Expected {len(texts)} embeddings, got {len(embeddings)}"
        )
    return embeddings
