import httpx

OLLAMA_BASE = "http://localhost:11434"
DEFAULT_EMBED_MODEL = "nomic-embed-text"


def _ollama_not_running() -> RuntimeError:
    return RuntimeError(
        "Cannot reach Ollama at localhost:11434. "
        "Please start Ollama with `ollama serve` and try again."
    )


def embed_one(text: str, model: str = DEFAULT_EMBED_MODEL) -> list[float]:
    """Return an embedding vector for a single string."""
    try:
        response = httpx.post(
            f"{OLLAMA_BASE}/api/embeddings",
            json={"model": model, "prompt": text},
            timeout=60.0,
        )
        response.raise_for_status()
    except httpx.ConnectError:
        raise _ollama_not_running()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Ollama embedding error: {e.response.text}") from e

    data = response.json()
    return data["embedding"]


def embed_batch(
    texts: list[str], model: str = DEFAULT_EMBED_MODEL
) -> list[list[float]]:
    """Return embedding vectors for a list of strings (one request per string)."""
    return [embed_one(text, model) for text in texts]
