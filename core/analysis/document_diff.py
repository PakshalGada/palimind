import re
import difflib
import math
from typing import Any
from core.retrieval.embedder import generate_embeddings_batch

def _split_sentences(text: str) -> list[str]:
    # Simple regex to split by sentence
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sentences if s.strip()]

def _cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    dot = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)

def compute_diff(text1: str, text2: str, ollama_url: str, embed_model: str) -> dict[str, list[str]]:
    """
    Compare two texts (e.g. 2023 vs 2025) and return a diff dictionary.
    Uses exact text matching + semantic similarity to find added/removed/modified statements.
    """
    s1 = _split_sentences(text1)
    s2 = _split_sentences(text2)
    
    if not s1 and not s2:
        return {"added": [], "removed": [], "modified": []}
        
    # Extract exact matches
    matcher = difflib.SequenceMatcher(None, s1, s2)
    
    added = []
    removed = []
    modified = []
    
    unmatched_s1 = []
    unmatched_s2 = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            pass
        elif tag == 'delete':
            unmatched_s1.extend(s1[i1:i2])
        elif tag == 'insert':
            unmatched_s2.extend(s2[j1:j2])
        elif tag == 'replace':
            unmatched_s1.extend(s1[i1:i2])
            unmatched_s2.extend(s2[j1:j2])
            
    if not unmatched_s1:
        return {"added": unmatched_s2, "removed": [], "modified": []}
    if not unmatched_s2:
        return {"added": [], "removed": unmatched_s1, "modified": []}
        
    # We have unaligned sentences on both sides.
    # Compute embeddings to find semantic matches
    try:
        all_texts = unmatched_s1 + unmatched_s2
        embeddings = generate_embeddings_batch(all_texts, ollama_url, embed_model)
        
        emb1 = embeddings[:len(unmatched_s1)]
        emb2 = embeddings[len(unmatched_s1):]
        
        matched_s2_indices = set()
        
        for i, (sent1, e1) in enumerate(zip(unmatched_s1, emb1)):
            if not e1:
                removed.append(sent1)
                continue
            
            best_sim = 0.0
            best_idx = -1
            
            for j, (sent2, e2) in enumerate(zip(unmatched_s2, emb2)):
                if not e2 or j in matched_s2_indices:
                    continue
                sim = _cosine_similarity(e1, e2)
                if sim > best_sim:
                    best_sim = sim
                    best_idx = j
            
            if best_sim > 0.85:
                # Highly similar, consider it modified
                matched_s2_indices.add(best_idx)
                modified.append(f"From: {sent1} -> To: {unmatched_s2[best_idx]}")
            else:
                removed.append(sent1)
                
        for j, sent2 in enumerate(unmatched_s2):
            if j not in matched_s2_indices:
                added.append(sent2)
                
    except Exception as e:
        # Fallback to simple difflib results if embeddings fail
        removed = unmatched_s1
        added = unmatched_s2

    return {
        "added": added,
        "removed": removed,
        "modified": modified
    }
