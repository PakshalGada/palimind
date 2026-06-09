import re

def chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """
    Chunks text into sizes of roughly `chunk_size` characters, overlapping by `chunk_overlap`.
    Snaps to word boundaries.
    """
    if not text:
        return []
        
    chunks = []
    start = 0
    text_length = len(text)
    
    while start < text_length:
        prev_start = start
        end = start + chunk_size
        
        if end >= text_length:
            chunks.append(text[start:].strip())
            break
            
        # Try to find a word boundary to snap to (space or newline)
        match = re.search(r'\s+', text[end-50:end+50])
        if match:
            # Snap end to the matched whitespace
            boundary = (end - 50) + match.start()
            if boundary > start:
                end = boundary
                
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
            
        start = end - chunk_overlap
        
        # Prevent infinite loops if overlap is too large
        if start <= prev_start:
            start = end
            
    return chunks
