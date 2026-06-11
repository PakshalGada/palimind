from typing import Dict, Any, List
import re

def chunk_text(text: str, chunk_size_chars: int = 3200, overlap_chars: int = 400) -> list[str]:
    chunks = []
    start = 0
    text_len = len(text)
    
    if text_len == 0:
        return []
        
    while start < text_len:
        end = start + chunk_size_chars
        if end >= text_len:
            chunks.append(text[start:].strip())
            break
            
        break_point = end
        for i in range(end, max(start, end - 200), -1):
            if text[i] in ("\\n", " "):
                break_point = i
                break
                
        chunks.append(text[start:break_point].strip())
        start = break_point - overlap_chars
        
    return [c for c in chunks if c]

def section_aware_chunking_from_tree(doc_name: str, structure: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Chunks based directly on the hierarchical section tree.
    Target 800-1200 tokens (3200-4800 chars), overlap 100-200 tokens (400-800 chars).
    Never splits titles from content.
    Returns list of dicts with section and subsection metadata.
    """
    results = []
    
    sections = structure.get("sections", [])
    
    for major in sections:
        major_title = major.get("title", "")
        major_text = major.get("text", "")
        major_page = major.get("page", 1)
        
        # Chunk the major section text directly
        if major_text.strip():
            text_chunks = chunk_text(major_text, chunk_size_chars=4000, overlap_chars=600)
            for i, chk in enumerate(text_chunks):
                final_text = f"{major_title}\\n\\n{chk}" if i == 0 else chk
                results.append({
                    "document": doc_name,
                    "section": major_title,
                    "subsection": "",
                    "page": major_page,
                    "text": final_text
                })
                
        # Now chunk the subsections
        for minor in major.get("subsections", []):
            minor_title = minor.get("title", "")
            minor_text = minor.get("text", "")
            minor_page = minor.get("page", 1)
            
            if minor_text.strip():
                text_chunks = chunk_text(minor_text, chunk_size_chars=4000, overlap_chars=600)
                for i, chk in enumerate(text_chunks):
                    final_text = f"{minor_title}\\n\\n{chk}" if i == 0 else chk
                    results.append({
                        "document": doc_name,
                        "section": major_title,
                        "subsection": minor_title,
                        "page": minor_page,
                        "text": final_text
                    })
                    
    return results
