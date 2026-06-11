import re
from typing import TypedDict, List, Optional

class MetadataFilter(TypedDict):
    years: List[int]
    sections: List[str]
    document_names: List[str]
    is_comparison: bool

# Known standard section headers in financial or general docs
KNOWN_SECTIONS = [
    "Competition",
    "Risk Factors",
    "Supply of Components",
    "Management's Discussion",
    "Financial Statements",
    "Executive Overview",
    "Legal Proceedings"
]

def extract_metadata_from_query(query: str) -> MetadataFilter:
    """
    Extract metadata filters deterministically using Regex and keyword matching.
    < 2ms latency guaranteed (no LLMs).
    """
    # Extract years (4 digit numbers between 1990 and 2050)
    years = []
    for match in re.finditer(r"\b(19[9][0-9]|20[0-4][0-9]|2050)\b", query):
        years.append(int(match.group(1)))
        
    years = sorted(list(set(years)))
    
    # Extract sections using simple substring or normalized matching
    query_lower = query.lower()
    sections = []
    for sec in KNOWN_SECTIONS:
        if sec.lower() in query_lower:
            sections.append(sec)
            
    # Detect comparison
    comparison_keywords = {"compare", "difference", "change", "added", "removed", "new", "evolution", "timeline", "vs"}
    is_comparison = any(kw in query_lower for kw in comparison_keywords)
    
    return {
        "years": years,
        "sections": sections,
        "document_names": [], # Could extract specific document names if needed
        "is_comparison": is_comparison
    }
