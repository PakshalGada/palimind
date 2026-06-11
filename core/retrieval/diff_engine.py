import re
import difflib

try:
    from rapidfuzz import fuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False

def _split_sentences(text: str) -> list[str]:
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sentences if s.strip()]

def fast_text_diff(text1: str, text2: str) -> dict[str, list[str]]:
    """
    Very fast diff engine (< 20ms) using difflib and optionally rapidfuzz.
    Does not use LLMs or heavy embeddings unless absolutely necessary.
    """
    s1 = _split_sentences(text1)
    s2 = _split_sentences(text2)
    
    if not s1 and not s2:
        return {"added": [], "removed": [], "modified": []}
        
    added = []
    removed = []
    modified = []
    
    # 1. Exact textual match using difflib
    matcher = difflib.SequenceMatcher(None, s1, s2)
    
    unmatched_s1 = []
    unmatched_s2 = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'delete':
            unmatched_s1.extend(s1[i1:i2])
        elif tag == 'insert':
            unmatched_s2.extend(s2[j1:j2])
        elif tag == 'replace':
            unmatched_s1.extend(s1[i1:i2])
            unmatched_s2.extend(s2[j1:j2])
            
    # 2. Heuristic similarity for modified vs added/removed
    # If rapidfuzz is available, use it. Otherwise rely on difflib ratio.
    matched_s2_indices = set()
    
    for sent1 in unmatched_s1:
        best_sim = 0.0
        best_idx = -1
        
        for j, sent2 in enumerate(unmatched_s2):
            if j in matched_s2_indices:
                continue
            
            if HAS_RAPIDFUZZ:
                sim = fuzz.ratio(sent1, sent2) / 100.0
            else:
                sim = difflib.SequenceMatcher(None, sent1, sent2).ratio()
                
            if sim > best_sim:
                best_sim = sim
                best_idx = j
                
        # High threshold for purely text-based similarity
        if best_sim > 0.65:
            matched_s2_indices.add(best_idx)
            modified.append(f"From: {sent1} -> To: {unmatched_s2[best_idx]}")
        else:
            removed.append(sent1)
            
    for j, sent2 in enumerate(unmatched_s2):
        if j not in matched_s2_indices:
            added.append(sent2)
            
    return {
        "added": added,
        "removed": removed,
        "modified": modified
    }
