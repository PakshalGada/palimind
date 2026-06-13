import difflib

def compute_diff(text1: str, text2: str, label1: str = "Doc 1", label2: str = "Doc 2") -> str:
    """
    Perform a strict line-by-line deterministic diff between two texts.
    Returns a unified diff string. No LLM summarization.
    """
    lines1 = text1.splitlines()
    lines2 = text2.splitlines()
    
    diff = difflib.unified_diff(
        lines1, lines2, 
        fromfile=label1, tofile=label2, 
        lineterm=""
    )
    
    return "\n".join(diff)

def compare_chunks(chunks1: list[dict], chunks2: list[dict], label1: str = "Doc 1", label2: str = "Doc 2") -> str:
    """
    Compare two lists of chunks. Merges content before diffing.
    """
    text1 = "\n".join([c.get("content", "") for c in chunks1])
    text2 = "\n".join([c.get("content", "") for c in chunks2])
    return compute_diff(text1, text2, label1, label2)
