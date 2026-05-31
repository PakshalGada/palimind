from pathlib import Path
from core.storage.vector_store import search
from core.retrieval.embedder import generate_embedding
from core.config import load_config

def retrieve_context(query: str, root: Path, limit: int = 5) -> dict:
    """
    Retrieve relevant chunks for a query.
    Returns a dict with 'text_contexts' and 'image_paths'.
    """
    config = load_config(root)
    ollama_url = config.get("ollama_base_url", "http://localhost:11434")
    embed_model = config.get("embed_model", "nomic-embed-text")
    
    query_vector = generate_embedding(query, ollama_url, embed_model)
    if not query_vector:
        return {"text_contexts": [], "image_paths": []}
        
    results = search(root, query_vector, limit=limit)
    
    text_contexts = []
    image_paths = set()
    
    for row in results:
        chunk_type = row.get("chunk_type", "text")
        content = row.get("content", "")
        file_path = row.get("file_path", "")
        
        if chunk_type in ["text", "caption"]:
            text_contexts.append(f"Source ({file_path}):\n{content}")
            if chunk_type == "caption":
                image_paths.add(file_path)
        elif chunk_type == "image":
            image_paths.add(file_path)
            
    return {
        "text_contexts": text_contexts,
        "image_paths": list(image_paths)
    }
