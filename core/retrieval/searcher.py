import numpy as np

from .store import Store

DEFAULT_K = 5


def _normalize(matrix: np.ndarray) -> np.ndarray:
    """L2-normalize each row. Rows with zero norm are left as-is."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return matrix / norms


def search(
    query_embedding: list[float],
    store: Store,
    k: int = DEFAULT_K,
) -> list[tuple[int, float]]:
    """
    Return the top-k (chunk_id, score) pairs sorted by cosine similarity desc.
    Returns an empty list if the index is empty.
    """
    matrix, ids = store.load_all_embeddings()

    if len(ids) == 0:
        return []

    query = np.array(query_embedding, dtype=np.float32)
    query_norm = query / (np.linalg.norm(query) or 1.0)

    matrix_norm = _normalize(matrix)
    scores = matrix_norm @ query_norm  # shape (N,)

    top_k = min(k, len(ids))
    top_indices = np.argpartition(scores, -top_k)[-top_k:]
    top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]

    return [(ids[i], float(scores[i])) for i in top_indices]
